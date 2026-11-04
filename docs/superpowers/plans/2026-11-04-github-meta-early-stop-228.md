# GitHub meta の展開の失敗をルールを消す前に止める 実装計画（#228・#229）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `init-firewall.sh` の init モードが、形の崩れた GitHub meta のスナップショット（単一の JSON オブジェクトでない、`.web`・`.api`・`.git` が文字列の配列でない、IPv4 らしい値が範囲外、IPv4 の範囲が 0 件、範囲の展開の失敗）で、最初の `iptables -F` の後まで進まないようにする（#228）。`verify_ipv4()` の api.github.com の解決の失敗を固定入力のテストで起こせるようにし、`dig` の失敗も ERROR と rc 1 で止める（#229）。あわせて PR #235 の未対応の Minor（`resolve_allowed_ports()` の前のコメント）を直す。

**Architecture:** `load_github_ranges()` の検査を `jq -s` で「単一のオブジェクトで、3 つが文字列の配列」まで強め、展開をコマンド置換で受けて終了コードを取り、IPv4 らしい値（`IPV4_CIDR_RE` に合うもの）のオクテットとプレフィックスの範囲を確かめ、正しい IPv4 の範囲が 1 件も無ければ止める。どれも `full_init()` の `reset_ipv4_rules`（最初の `iptables -F`）より前に起きる。IPv6 などの IPv4 らしくない値は、今と同じく `add_cidr()` が読み飛ばす。`verify_ipv4()` は `dig` の失敗を空の結果と同じ経路（ERROR と rc 1）に流す。テストは既存の `tests/test-firewall-init-trace.sh` にシナリオ、出力の照合、`jq` のスタブを足す。

**Tech Stack:** bash、jq、iptables（スタブ）、既存の trace テスト。

**Spec:** Issue #228・#229 の本文（2026-11-04 時点）と、PR #235 の未対応の Minor。別の設計文書は作らない（持ち主が会話で承認した要約が仕様）。

## Global Constraints

**REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（Task 1 の前に 1 回）

- 作業ブランチは `fix/228-github-meta-early-stop`（`main` の 5ec7597 から作る。Task 0）。
- `docs/development-invariants.md` の「`init-firewall.sh`」の項と「コアスクリプトの不変条件」を守る（fail-closed、ポート制限は `CHAIN` 経由のルールだけ、GitHub の範囲はビルド時スナップショットの読み込みだけでライブ取得を足さない）。
- 成功する入力のときの、ルールを変える呼び出しの列は変えない。既存の `tests/fixtures/firewall-init-trace/*.expected` は 1 バイトも変えない（`git diff --exit-code tests/fixtures/firewall-init-trace/` で確かめる。新しいファイルの追加だけを許す）。`UPDATE_EXPECTED=1` は使わない。
- `verify_ipv4()` は名前を残し、本体の中で完結させる（ほかの関数・変数を呼ばない）。`tests/test_ipv6_shell.py`・`tests/test_network_timeouts.py` が本体だけを抜き出して走らせるため。`dig`・`curl`・`timeout` の呼び出しの形（引数）は変えない。
- ルールを入れる関数を `if`・`||`・`&&` の条件の中から呼ばない（条件の中では関数の中の `set -e` が効かない）。
- 既存のエラーの文言は変えない。例外は Task 2 Step 3 の 1 つだけ。新しい文言は下の Task に逐語で書いたものにする（テストとドキュメントは今の文言を照合していない。計画者が `grep -rn` で確かめた）。
- 範囲外: `c3c` の `stage_build_context()` の meta の検査（同じ `.web and .api and .git` の弱い検査）は変えない。init 側が実行時の関門で、ビルド側を強めるのは別の変更とする（PR 本文の「範囲外」に書く）。
- 文書とコメントは日本語（README「表記」節）。挙動を変えたら README の該当節を同じ commit で直す（root `AGENTS.md`）。
- ファイルを編集したら、そのターン内で `./lint.sh` を実行し、rc 0・警告ゼロを確かめる（コンテナ内では Compose 検証が警告付きでスキップされる。その場合は Compose 検証を `not run` と報告する）。
- テストのコマンドは、どれもリポジトリのルート（`/workspace` か worktree のルート）で実行する。

## Review Focus

- `.web`・`.api`・`.git` のどれかが配列でない、または要素が文字列でない meta → ルールを 1 つも変えずに rc 1。Task 1 の `meta-not-array`・`meta-non-string`。
- 複数の JSON 値を連結したスナップショット（`jq -e` は最後の値で判定するので、今の形の検査は最初の不正な値を通す。計画のレビューで rc 0 を確かめた）→ rc 1。Task 1 の `meta-concatenated`。
- 字面は IPv4 だが範囲外（`300.1.1.1/8`、`1.2.3.4/40`）→ 今の版では `add_cidr()` の正規表現を通り、`iptables -F` の後の `iptables -A` まで進む。Task 1 の `meta-bad-octet`・`meta-bad-prefix` で、ルールを変えずに止まることを固定する。
- 3 つとも配列だが IPv4 の範囲が 0 件（空の配列、IPv6 だけ）→ Task 1 の `meta-no-ipv4`。
- api.github.com の解決が空（`dig` は rc 0）と、`dig` 自体の失敗（rc 9）→ どちらも ERROR を出して rc 1。今は後者が `set -e` で `dig` の rc（9）のまま、ERROR を出さずに終わる。Task 2。

---

### Task 0: ブランチを作り、承認された計画を公開の置き場へ置く

**REQUIRED SUB-SKILL:** Use superpowers:using-git-worktrees（並行するセッションが無ければ `/workspace` で `git switch -c` してよい）

- [ ] **Step 1: ブランチを作る**

  Run: `git status --short; git switch -c fix/228-github-meta-early-stop 5ec7597`
  Expected: `git status --short` の出力が空、ブランチが作られる。

- [ ] **Step 2: 計画を置く**

  計画ファイルを `docs/superpowers/plans/2026-11-04-github-meta-early-stop-228.md` へ写す。記録節の一時パスは、`/tmp/claude-1000/-workspace/<セッション ID>/` を `<scratchpad>/` に置き換える（前例: `docs/superpowers/plans/2026-10-27-license-provenance-rewrite-225.md` の記録節）。`grep -nE '/home/|/shared/|/tmp/|c3c-ops|obsidian|_PAT' <写し>` の出力が空であることを確かめる。

  ```bash
  git add docs/superpowers/plans/2026-11-04-github-meta-early-stop-228.md
  git commit -m "docs: GitHub meta の展開の失敗を、ルールを消す前に止める計画（#228・#229）"
  ```

### Task 1: meta の検査を強め、ルールを消す前に止める（#228）

**Files:**
- Modify: `init-firewall.sh`（`add_cidr()` の前に定数を置き、`add_cidr()` の正規表現をその定数に替える。`load_github_ranges()` とその前のコメント）
- Modify: `README.md`（「GitHub meta スナップショット」節の段落の末尾に 1 文）
- Test: `tests/test-firewall-init-trace.sh`（`jq` のスタブ、出力を照合する関数、シナリオ 7 つ）

**Interfaces:**
- Produces: `readonly IPV4_CIDR_RE='^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(/[0-9]{1,2})?$'`（`init-firewall.sh` の、`add_cidr()` の直前のコメントの前。今の `add_cidr()` の正規表現と同じ文字列で、`add_cidr()` と `load_github_ranges()` が `[[ $x =~ $IPV4_CIDR_RE ]]` の形で使う）。
- Produces: テストの関数 `expect_output <シナリオ名> <固定文字列>`（直前に走らせたシナリオの標準出力・標準エラー `$tmp/<名前>.out` に、固定文字列が含まれなければ `FAIL: <名前>: 出力に「<文字列>」がありません` を出して `fail` を 1 増やす。`grep -qF -- "$2" "$tmp/$1.out"` で探す）。Task 2 も使う。
- Produces: テストの `jq` のスタブ（`$stubs/jq`）。`TRACE_JQ_EXPAND_FAIL=1` のとき、第 1 引数が `-r` の呼び出しにだけ `140.82.112.0/20` を 1 行出して rc 5 で終わる。それ以外は本物の `jq` に `exec` する（本物のパスは、スタブを作る前に `command -v jq` で取り、スタブに埋め込む）。

- [ ] **Step 1: 失敗するテストを書く**

  - `dig` のスタブの後に `jq` のスタブを足す（Interfaces のとおり）。
  - `expect_ipv6_conf()` の後に `expect_output()` を足す。
  - 「ルールを変える前に止まる」の節の `no-default-route` の後に次を足す。各シナリオで、共通の接頭辞と、検査ごとに固有の部分を別々に照合する（文言の途中にスナップショットのパスが入るため）。

  ```bash
  m='ERROR: GitHub meta のスナップショット'
  run_scenario meta-not-array early -- 'TRACE_META={"web":1,"api":1,"git":1}'
  expect_output meta-not-array "$m"; expect_output meta-not-array 'がないか不正です'
  run_scenario meta-non-string early -- 'TRACE_META={"web":[1],"api":["140.82.112.0/20"],"git":[]}'
  expect_output meta-non-string "$m"; expect_output meta-non-string 'がないか不正です'
  run_scenario meta-concatenated early -- 'TRACE_META={"web":[1],"api":[],"git":[]} {"web":["192.30.252.0/22"],"api":[],"git":[]}'
  expect_output meta-concatenated "$m"; expect_output meta-concatenated 'がないか不正です'
  run_scenario meta-bad-octet early -- 'TRACE_META={"web":["300.1.1.1/8"],"api":["140.82.112.0/20"],"git":[]}'
  expect_output meta-bad-octet "$m"; expect_output meta-bad-octet '不正な IPv4 の範囲があります: 300.1.1.1/8'
  run_scenario meta-bad-prefix early -- 'TRACE_META={"web":["1.2.3.4/40"],"api":["140.82.112.0/20"],"git":[]}'
  expect_output meta-bad-prefix "$m"; expect_output meta-bad-prefix '不正な IPv4 の範囲があります: 1.2.3.4/40'
  run_scenario meta-no-ipv4 early -- 'TRACE_META={"web":[],"api":["2a0a:a440::/29"],"git":[]}'
  expect_output meta-no-ipv4 "$m"; expect_output meta-no-ipv4 'に IPv4 の範囲がありません'
  run_scenario meta-expand-fails early -- TRACE_JQ_EXPAND_FAIL=1
  expect_output meta-expand-fails "$m"; expect_output meta-expand-fails 'の範囲を展開できませんでした'
  ```

  - 先頭のコメントの「bad-meta・no-default-route は、ルールを 1 つも変えずに止まることを判定する」に、7 つの名前（`meta-*`）を足す。

- [ ] **Step 2: 失敗を確かめる**

  **REQUIRED SUB-SKILL:** Use superpowers:systematic-debugging（Expected と違う FAIL が出たら、その場で原因を調べる）

  Run: `bash tests/test-firewall-init-trace.sh; echo rc=$?`
  Expected: rc=1。7 つの新しいシナリオのそれぞれに `FAIL: <名前>: rc=1 で止まるべきところ rc=0` と出力の FAIL が出る（今の版は検査をすべて通り、自己検証のスタブも通るため）。既存の 16 シナリオには FAIL が出ない。

- [ ] **Step 3: `load_github_ranges()` を直す**

  - 検査を次の式に替える（`-s` で全入力を 1 つの配列にし、値が 1 つだけでオブジェクトであることも確かめる。空の入力は `length == 1` で落ちる）。失敗したときの文言は今の `ERROR: GitHub meta のスナップショット $GITHUB_META_SNAPSHOT がないか不正です` のまま。

    ```bash
    jq -se 'length == 1 and (.[0] | type == "object") and ([.[0].web, .[0].api, .[0].git] | all(type == "array" and all(.[]; type == "string")))'
    ```

  - 展開は `local expanded` を宣言してから `if ! expanded=$(printf '%s\n' "$meta" | jq -r '(.web + .api + .git)[]' | sort -u); then` で受け、失敗したら `ERROR: GitHub meta のスナップショット $GITHUB_META_SNAPSHOT の範囲を展開できませんでした` を出して `exit 1`。`expanded` が空でなければ `mapfile -t GITHUB_CIDRS <<< "$expanded"`、空なら `GITHUB_CIDRS=()`。
  - `GITHUB_CIDRS` の各要素のうち `IPV4_CIDR_RE` に合うものについて、4 つのオクテットがどれも 255 以下で、プレフィックスがあれば 32 以下であることを確かめる（十進数として `10#` で評価する。`resolve_allowed_ports()` と同じ書き方）。外れたら `ERROR: GitHub meta のスナップショット $GITHUB_META_SNAPSHOT に不正な IPv4 の範囲があります: <その要素>` で `exit 1`。合うものを数え、0 件なら `ERROR: GitHub meta のスナップショット $GITHUB_META_SNAPSHOT に IPv4 の範囲がありません` で `exit 1`。`IPV4_CIDR_RE` に合わない要素（IPv6 など）は今と同じく残し、`add_cidr()` が読み飛ばす。
  - 関数の前のコメントに、「形・値の範囲・IPv4 の件数まで確かめ、ここで止まれば既存のルールには手を付けない（#228）」の趣旨を 1〜2 行で足す。
  - `add_cidr()` の正規表現を `IPV4_CIDR_RE` に替える（同じ文字列なので挙動は変わらない）。

- [ ] **Step 4: README を直す**

  README.md「GitHub meta スナップショット」節の段落（「`init-firewall.sh` の許可リストが使う…」で始まる 1 段落）の末尾に、次の 1 文を足す。

  > コンテナ起動時の `init-firewall.sh` は、スナップショットが単一の JSON オブジェクトで `web`・`api`・`git` が文字列の配列であること、IPv4 の範囲の値が正しく 1 件以上あることを、既存のルールを消す前に確かめ、満たさなければ起動を止める。

- [ ] **Step 5: 通ることを確かめる**

  Run: `bash tests/test-firewall-init-trace.sh; echo rc=$?; git diff --exit-code tests/fixtures/firewall-init-trace/; echo diff_rc=$?`
  Expected: `OK: 23 シナリオ`（既存 16 + 7）と rc=0、diff_rc=0。違えば Step 2 と同じく原因を調べる。

- [ ] **Step 6: lint と commit**

  Run: `./lint.sh; echo rc=$?` → rc=0、警告ゼロ（Compose のスキップの警告を除く）。

  ```bash
  git add init-firewall.sh README.md tests/test-firewall-init-trace.sh
  git commit -m "fix: 形の崩れた GitHub meta のスナップショットで、ルールを消す前に止める（#228）"
  ```

### Task 2: api.github.com の解決の失敗をテストで起こし、rc 1 と ERROR に揃える（#229）

**Files:**
- Modify: `init-firewall.sh`（`verify_ipv4()` の `github_ipv4=$(...)` の行と、直後の `-z` の検査の ERROR の文言）
- Modify: `tests/test-firewall-init-trace.sh`（`dig` のスタブ、シナリオ 2 つ）
- Create: `tests/fixtures/firewall-init-trace/verify-github-dig-empty.expected`、`tests/fixtures/firewall-init-trace/verify-github-dig-fails.expected`

**Interfaces:**
- Consumes: Task 1 の `expect_output`。
- Produces: スタブの切り替え `TRACE_VERIFY=github-dig-empty`（api.github.com の解決で何も出さず rc 0）と `TRACE_VERIFY=github-dig-fails`（何も出さず rc 9）。

- [ ] **Step 1: 失敗するテストを書く**

  - `dig` のスタブの api.github.com の分岐で、`TRACE_VERIFY` が `github-dig-empty` なら `exit 0`、`github-dig-fails` なら `exit 9` を、`echo 140.82.112.5` の前に置く。
  - 「自己検証」の節の `verify-github80-reachable` の後に足す。

  ```bash
  run_scenario verify-github-dig-empty full -- TRACE_VERIFY=github-dig-empty
  expect_output verify-github-dig-empty 'ERROR: ファイアウォール検証に失敗しました。api.github.com の IPv4 アドレスを解決できません'
  run_scenario verify-github-dig-fails full -- TRACE_VERIFY=github-dig-fails
  expect_output verify-github-dig-fails 'ERROR: ファイアウォール検証に失敗しました。api.github.com の IPv4 アドレスを解決できません'
  ```

  - 期待値ファイルは、`ipv4-resolver.expected` の最終行 `rc=0` を `rc=1` に替えた写しにする（`verify-example-reachable.expected` と同じ中身になる。計画者が `diff` で、この 2 つの違いが最終行の rc だけであることを確かめた）。

    ```bash
    d=tests/fixtures/firewall-init-trace
    sed '$s/^rc=0$/rc=1/' "$d/ipv4-resolver.expected" > "$d/verify-github-dig-empty.expected"
    sed '$s/^rc=0$/rc=1/' "$d/ipv4-resolver.expected" > "$d/verify-github-dig-fails.expected"
    cmp "$d/verify-github-dig-empty.expected" "$d/verify-example-reachable.expected"; echo cmp=$?
    ```

    Expected: cmp=0。

- [ ] **Step 2: 失敗を確かめる**

  **REQUIRED SUB-SKILL:** Use superpowers:systematic-debugging（Expected と違う FAIL が出たら、その場で原因を調べる）

  Run: `bash tests/test-firewall-init-trace.sh; echo rc=$?`
  Expected: rc=1。`verify-github-dig-empty` は記録の照合は通り（今の版でも空なら rc 1）、出力の FAIL だけが出る（今の文言は「api.github.com:443 へ到達できません」）。`verify-github-dig-fails` は期待値の差分（`-rc=1` / `+rc=9`）と出力の FAIL が出る。それ以外に FAIL は無い。

- [ ] **Step 3: `verify_ipv4()` を直す**

  `github_ipv4=$(dig ... | awk ...)` の行の末尾に `|| github_ipv4=''` を足し、`dig` の失敗を直後の `-z` の検査へ流す。`dig` と `awk` の引数は変えない。この `-z` の検査の ERROR の文言を `ERROR: ファイアウォール検証に失敗しました。api.github.com の IPv4 アドレスを解決できません` に替える（今の「api.github.com:443 へ到達できません」は、接続を試す前の解決の失敗を指していて紛らわしいため。443 の接続の検査の文言は変えない）。その上のコメントに、解決の失敗も空と同じく止める旨を 1 行足す。

- [ ] **Step 4: 通ることを確かめる**

  Run: `bash tests/test-firewall-init-trace.sh; echo rc=$?; git diff --exit-code tests/fixtures/firewall-init-trace/; echo diff_rc=$?; git status --short tests/fixtures/; PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_ipv6_shell.py'; echo py1=$?; PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_network_timeouts.py'; echo py2=$?`
  Expected: `OK: 25 シナリオ` と rc=0、diff_rc=0、`git status --short tests/fixtures/` に新しい 2 つだけが `??` で出る、py1=0、py2=0。

- [ ] **Step 5: lint と commit**

  Run: `./lint.sh; echo rc=$?` → rc=0。

  ```bash
  git add init-firewall.sh tests/test-firewall-init-trace.sh tests/fixtures/firewall-init-trace/verify-github-dig-empty.expected tests/fixtures/firewall-init-trace/verify-github-dig-fails.expected
  git commit -m "test: api.github.com の解決の失敗をテストで起こし、dig の失敗も ERROR と rc 1 で止める（#229）"
  ```

  README の自己検証の節（「IPv4 起動時の HTTPS 自己検証は」で始まる段落）は api.github.com の解決に触れていないので、直さない。

### Task 3: `resolve_allowed_ports()` の前のコメントを関数ごとに書き分ける（PR #235 の Minor）

**Files:**
- Modify: `init-firewall.sh`（`resolve_allowed_ports() {` の直前のコメント 5 行。`grep -n '^resolve_allowed_ports' init-firewall.sh` で探す）

- [ ] **Step 1: コメントを置き換える**

  直前の 5 行を、次の 5 行に置き換える（逐語）。

  ```bash
  # CHAIN 経由の ACCEPT ルール（下の add_cidr/add_cidr_tagged）が、それ以外は許可された
  # IP に対して許可するポート（#31）。init モードと --refresh-domains モードの
  # 両方が同じ値を見るよう、ここで一度だけ読む。DNS リゾルバのルールと
  # ホストネットワークのルールには適用されず、制限なしのままとなる。どちらも CHAIN を
  # 通さずに直接入れる（allow_dns() は OUTPUT だけ、allow_host_gateway() は INPUT と OUTPUT）。
  ```

- [ ] **Step 2: 確かめて commit**

  Run: `./lint.sh; echo rc=$?; bash tests/test-firewall-init-trace.sh; echo rc2=$?; git diff HEAD -- init-firewall.sh`
  Expected: rc=0、rc2=0（`OK: 25 シナリオ`）、差分の `-`・`+` の行がどれも `#` で始まるコメントの行だけ。

  ```bash
  git add init-firewall.sh
  git commit -m "docs: resolve_allowed_ports() の前のコメントを、DNS とゲートウェイの関数ごとに書き分ける（PR #235 の Minor）"
  ```

### Task 4: 全体の検証、PR 前の二重レビュー、PR

- [ ] **Step 1: 全体の検証**

  **REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:systematic-debugging（想定外の失敗が出たとき、その場で原因を調べる）

  Run: `./lint.sh; echo lint=$?; ./test-build.sh --launcher-only; echo launcher=$?; git diff --exit-code main -- tests/fixtures/firewall-init-trace/ ':!tests/fixtures/firewall-init-trace/verify-github-dig-*.expected'; echo fixtures=$?`
  Expected: lint=0、launcher=0、fixtures=0。`--launcher-only` が環境の制約で走らなければ、理由を付けて `not run` とし、PR 本文に書く（CI が同じものを走らせる）。

- [ ] **Step 2: PR 前の二重レビュー（区分が境界のため）**

  **REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review（結果を受け取って反映するとき）

  グローバル `AGENTS.md`「モデルと実装者の使い分け」の既定の順で、claude-review skill と codex-review skill（`--provider openai -m gpt-6.1-sol`）を、`main...HEAD` の差分で起動する。Critical・Important を直し、出したレビュアーに確認限定巡を頼む。Codex 側が起動できない・起動後に失敗したときは、グローバル `AGENTS.md` の「Codex 側だけが使えないときの例外」に当たるかを判定し、当たらなければ止まって持ち主に報告する。初回の結果は `review-data` の表（`~/.agents/skills/review-data/SKILL.md`）に、所要と判定は vault の台帳 `knowledge/モデル別の実績.md` に書く。

- [ ] **Step 3: push と PR（push は持ち主の確認の後）**

  **REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:finishing-a-development-branch

  PR 本文: 区分（境界）、変えた挙動（形の崩れた meta・範囲外の IPv4・IPv4 0 件・展開の失敗はルールを消す前に止まる。`dig` の失敗は rc 9 で ERROR を出さずに終わっていたのが、ERROR と rc 1 になる）、範囲外（`c3c` のビルド側の検査）、PR 前の二重レビューの判定と未対応の Minor、`not run` の項目と理由、`Closes #228`・`Closes #229`。両レビュアーの全文を PR コメントに投稿する。

- [ ] **Step 4: 実コンテナの確認**

  push の後、`gh workflow run runtime.yml --ref fix/228-github-meta-early-stop` で実コンテナの手動検証を走らせ、結果を PR 本文に書く（`docs/runtime-ci.md` の手順）。権限で起動できなければ、持ち主にホストでの `c3c claude -b` の起動と、ファイアウォールの初期化の完了の表示を確かめてもらう。どちらもできなければ `not run` と理由を書く。PR 後の二重レビューは handover で別のセッションへ渡す。

---

## 計画レビューの記録

- Self-Review: シナリオの数の誤り（19→16）、使わない環境変数 `EXPECT_EARLY_STOP` の手順、using-git-worktrees の指定漏れ、エラーの文言を実装者に委ねていた点を修正
- 版: `plan-initial.md` `<scratchpad>/tasks/b4foohzfg.output`
- Claude（claude-opus-5-5、session `b9d6b81d-b21d-441c-b51a-e694f2f72fc8`、所要 134 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/b7p3qympw.output`
  - I1 字面は IPv4 だが範囲外の値（`300.1.1.1/8`・`1.2.3.4/40`）が `iptables -F` の後まで進む → 採用（オクテットとプレフィックスの範囲を確かめ、`meta-bad-octet`・`meta-bad-prefix` を追加）
  - I2 3 つの meta シナリオの出力照合が同じ接頭辞で、どの検査で止まったか見分けられない → 採用（検査ごとに固有の文言を照合）
  - M1 jq 式が例止まり → 採用（確定の式）。M2 展開の失敗の分岐に届くテストが無い → 採用（Codex I4 と同じ。`jq` のスタブ）。M3 `sed` の相対パス → 採用。M4 Step 2 の想定外の扱い → 採用（systematic-debugging）。M5 Codex 側が使えないときと台帳・review-data → 採用。M6 Spec の行の非公開の出典 → 採用（削除）。M7 折り返しの基準 → 採用（逐語の置き換え後の文面）。M8 README を直さない理由 → Codex I2 を採って README を直すので、理由の行は書かない
- Codex（gpt-6.1-sol、所要 147 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/b6tkiss7d.output`
  - I1 複数の JSON 値を連結すると形の検査をすり抜ける → 採用（計画者が再現: 今の式は rc 0、`jq -se` の式は rc 1。`meta-concatenated` を追加）
  - I2 挙動の変更に README の更新が無い → 採用（「GitHub meta スナップショット」節に 1 文）
  - I3 承認後に計画を公開の置き場へ置く手順が無い → 採用（Task 0）
  - I4 展開の途中の失敗の回帰テストが無い → 採用（`jq` のスタブと `meta-expand-fails`）
  - M1 コメントだけの変更を `--stat` では確かめられない → 採用（差分の本文を見る）。M2 DNS の失敗のテストが `ERROR:` を照合しない → 採用（文言の全体を照合）
- 確認限定巡 1: Codex（I1〜I4、所要 21 秒）→ すべて解消、実装に渡せる。生の出力 `<scratchpad>/tasks/bwkst1p7k.output`
- 確認限定巡 1: Claude（I1・I2、所要 16 秒）→ すべて解消、実装に渡せる。生の出力 `<scratchpad>/tasks/b1ssv2e7x.output`
- argon の並走: not run（このセッションは c3c のコンテナの中で、並走はホストの Claude のセッションの回だけが対象）

区分: 境界 — `init-firewall.sh` はエグレス制限の中心で、`docs/development-invariants.md` の fail-closed の不変条件に触れる。
推奨実装: Opus — 判定順の 1〜5 に当たらず、c3c の既定では Claude Code 面の Sonnet になるが、セキュリティ境界を含むのでグローバル指示の Opus を推す条件に当たる。Task 1〜3 は逐語に近く設計判断はほぼ残らないが、`set -e` と条件の中の呼び出し、検査の順番を誤ると境界が黙って緩むため。Codex（判定順の 4・5）は当たらないので推さない。実行方法は executing-plans（Task が 5 つと少なく、Task 2 が Task 1 の `expect_output` に依存する）。
実装: Opus（持ち主指定、2026-11-04。推奨どおり。このセッションの Opus 5.5 で executing-plans）
