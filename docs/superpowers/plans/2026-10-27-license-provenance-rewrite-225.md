# 上流と Anthropic の devcontainer から引き継いだコードの書き直し 実装計画（#225）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** フォーク元（MIT）の作者の行と、Anthropic の devcontainer を元にした部分を、挙動を変えずに c3c 自身の書き方で書き直し、`LICENSE` と README の帰属の表示を整理する。

**Architecture:** 書き直しの前に、`init-firewall.sh` の init モードを固定入力で走らせ、ルールを変える呼び出しの列を記録する回帰テストを作り、今の版の出力を期待値として commit する。その後に `init-firewall.sh`、`c3c`、`Dockerfile.claude`、`compose.yml` を書き直し、期待値・既存のテスト・実コンテナのルール一覧で、挙動が同じであることを確かめる。最後に表示を整理する。

**Tech Stack:** bash、iptables / ip6tables、Podman / podman-compose、Python unittest（既存のテスト）。

**Spec:** `docs/superpowers/specs/2026-10-27-license-provenance-rewrite-design.md`（99016d5）

## Global Constraints

**REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（Task 1 の前に 1 回。この計画では「失敗するテストを先に書く」の代わりに、書き直す前の版の挙動を期待値として固定し、書き直した後に同じ期待値で通す）

- 作業ブランチは `feat/license-provenance-225`（spec の commit 99016d5 を含む。作成済み）。
- 実装する人は、上流（sethjensen1/claude-container。`upstream` remote と `git show` を含む）と、anthropics/claude-code の `.devcontainer/` のファイルを開かない。どの行を書き直すかは、下の「書き直す行の一覧」で知る。
- 挙動・CLI 引数・`.c3c/` の設定形式・既定値・イメージの label・コンテナ内のパス・メッセージの接頭辞（`ERROR:` など）を変えない。README とテストが照合している文字列（例: `RUN DIR: `）も変えない。
- ルールを入れる順番は変えない。成功する入力のときのルールを変える呼び出し（`iptables`・`ip6tables` の `-F`・`-X`・`-N`・`-A`・`-D`・`-I`・`-P`、`-t` を含む）と `ipv6-firewall.py` の `prepare`・`refresh`・`verify` の、引数と順番は、Task 1 の期待値と一致させる。
- c3c の作者が書いた `init-firewall.sh` の関数（`resolve_allowed_ports`、`add_cidr`、`add_cidr_tagged`、`add_or_touch_domain_ip`、`build_domain_list`、`refresh_domains`、`prune_stale_domain_rules`、`do_refresh`）は、名前も中身も変えない。
- `verify_ipv4()` は名前を残し、本体の中で完結させる（ほかの関数を呼ばない）。`tests/test_ipv6_shell.py`・`tests/test_network_timeouts.py` が本体だけを抜き出して走らせ、`curl` の最後の引数が URL・api.anthropic.com 宛てに `-4`・`timeout` の最後の 2 引数が IP とポート・`dig` の出力を IPv4 の行で拾う、という形を前提にしているので、これらの呼び出しの形は変えない。
- ルールを入れる関数を `if`・`||`・`&&` の条件の中から呼ばない（bash は条件の中で呼んだ関数の中の `set -e` を効かせないので、途中の失敗が黙って通る）。
- `docs/development-invariants.md` の「`init-firewall.sh`」の項と「コアスクリプトの不変条件」を守る（fail-closed、ポート制限は `CHAIN` 経由のルールだけ、`host_network` は `/32`、IPv6 の遮断、`--refresh-domains` の rc 75 など）。
- git の履歴は書き換えない。`LICENSE` の GPL-3.0 の本文は変えない。
- 文書とコメントは日本語（README「表記」節）。`LICENSE` の法文と注記は英語でよい。
- ファイルを編集したら、そのターン内で `./lint.sh` を実行し、rc 0・警告ゼロを確かめる。
- 実コンテナの記録は、リポジトリの `tmp/225-pre/`・`tmp/225-post/`（`.gitignore` の `tmp` で追跡外）に置き、commit しない。

## 書き直す行の一覧（99016d5 の時点の行番号）

計画者が 2 つの方法で作った。(1) `git blame -w -M -C` でフォーク元の作者になる行（4 ファイル 49 行）。(2) 元ファイル（Anthropic の devcontainer の今の main と 2026-07-02 時点〈125d63f〉の `init-firewall.sh`・`Dockerfile`・`devcontainer.json`、上流の全 commit の全ファイル）との機械的な比較。一致の定義は、`#` 以降と前後の空白を除き、空行を除いた完全一致。(2) は 12 文字未満の定型（`fi`・`done`・`exit 1` など）を載せない（どのファイルにも現れる構文で、由来を示さないため）。対象の 4 ファイル以外で (2) に一致したのは `set -euo pipefail` とサービス名 `claude-auth-workspace:` だけで、どちらも「残」に当たる。

印: **書** = 書き直す、**残** = 字面が同じでよい（spec の「字面が同じでよいもの」）。空行は数に入るが、書き直しの対象にしない。

- `c3c`（blame 19 行: 8、68、135〜136、144〜147、184〜187、192、196、198〜201、264、2944〜2945）
  - 書: 8〜11（`BUILD=0` などの初期化の書き方）、130〜201（引数解析の `while`/`case` の組み立て。blame の 135〜201 の行を含む）、2944（`set -- ${POSITIONAL_ARGS[@]+…}`）
  - 残: 3（`set -euo pipefail`）、4・638・644（`trap 'exit 1' INT`。テストのコメントが前提にしている挙動）、2962（`echo "RUN DIR: $RUN_DIR"`。`tests/test_c3c_launch.py` が照合）。68・264・2945 は空行
- `Dockerfile.claude`（blame 15 行: 9、10、12、16、173、174、180〜182、388〜390、405、408）
  - 書: 180〜181（`/workspace` と `/home/node/.claude` の作成と所有者の設定）、345〜346（sudoers の書き込みと mode。(2) で一致）
  - 残: 10（`ARG CLAUDE_CODE_VERSION=latest`）、173（`ENV DEVCONTAINER=true`）、388（`WORKDIR /workspace`）、389（`USER node`）。9・12・16・174・182・390・405・408 は空行
- `compose.yml`（blame 14 行: 1、3、4、17〜19、37、39、58〜60、88、132）
  - 書: 37〜39 のコメントアウトされた `profiles`（使っていないので消す。38 行は c3c の作者のコメントで、一緒に消す）
  - 残: 1（`services:`）、3（サービス名）、4（`build:`）、17〜19（`stdin_open`・`tty`・`userns_mode`）、58（`volumes:`）、59・60・88（volume の 3 行）、132（`working_dir`）
- `.gitignore`（blame 1 行）
  - 残: 1（`tmp`）
- `init-firewall.sh`（blame 0 行。(2) で一致）
  - 書: 443（GitHub の範囲を 1 行ずつ読むループの書き方）
  - 書（構造）: `full_init()` 全体（376〜532 行）の関数の分け方と処理のまとまり、`verify_ipv4()`（337〜372 行）の本体の中の組み立て、冒頭のコメント（2〜19 行）
  - 残: 20（`set -euo pipefail`）、21（`IFS` の設定）、268・280（`refresh_domains` の中。c3c の作者の関数で、定型の構文）、389〜394・404〜407・416・471〜473・475（iptables のルールの引数）

## Review Focus

- `/etc/resolv.conf` に IPv4 のリゾルバが無いとき（IPv6 無効なら DNS を任意のホストへ許可する WARNING の経路、`--ipv6` なら INFO の経路）。書き直しで分岐を落としやすい。Task 1 の固定入力に入れる。
- `ip6tables -L` が失敗する環境（IPv6 無効のとき、ip6tables の遮断を飛ばして続ける経路）。書き直しで判定を落とすと `set -e` で止まるようになる。Task 1 に入れる。
- 途中の失敗（ルールの追加の失敗、IPv6 の DROP の失敗、許可ドメインの解決の失敗、IPv6 helper の失敗）で、rc 1 で、失敗した呼び出しの直後に止まること。GitHub meta の不正とデフォルトルートが無いときは、ルールを 1 つも変えずに止まること。関数を条件の中から呼ぶと黙って通る。Task 1 で失敗を注入する。
- `--ipv6` のとき、`ipv6-firewall.py` の `prepare`（DNS の許可の後・GitHub の範囲の前）、`refresh`（許可ドメインの解決の中）、`verify`（`verify_ipv4` の後）が今と同じ順で呼ばれること。Task 1 で照合する。
- `verify_ipv4` の 4 項目と上限時間。どれか 1 つが期待と違えば exit 1、全部が期待どおりなら成功。上限時間の引数が変われば差し替えのコマンドが失敗する。Task 1 で照合する。

---

### Task 1: 書き直す前の版でルールの組み立てを記録する回帰テスト

**Files:**
- Create: `tests/test-firewall-init-trace.sh`
- Create: `tests/fixtures/firewall-init-trace/`（シナリオごとの期待値ファイル `<scenario>.expected`）
- Modify: `test-build.sh`（882 行の `test-domain-rule-lifecycle.sh` の次に `check` を 1 行足す）

**Interfaces:**
- Produces: `bash tests/test-firewall-init-trace.sh`（rc 0 で全シナリオ合格）。`UPDATE_EXPECTED=1 bash tests/test-firewall-init-trace.sh` で成功シナリオの期待値を書き出す（期待値の作成は、この Task の中で今の版に対して 1 回だけ行う）。

- [ ] **Step 1: テストを書く**

  - 一時ディレクトリに `init-firewall.sh` を写し、`sed` で固定パス（`/etc/c3c/`、`/etc/resolv.conf`、`/usr/local/bin/ipv6-firewall.py`、`/proc/sys/net/ipv6/conf/`）を一時ディレクトリの下に置き換えて走らせる。元のファイルは変えない。写した後に元の固定パスが 1 つでも残っていたら、テストは失敗する。root（`id -u` が 0）では走らずに失敗する。`LC_ALL=C` で走らせる。
  - 写したスクリプトは `bash <写し> [--ipv6]` で直接起動する（条件の中や `|| true` で包まない。終了コードは起動の直後に `$?` で取る）。
  - `PATH` の先頭に差し替えのコマンドを置く:
    - `iptables`・`ip6tables`: ルールを変える呼び出しを `<コマンド> <引数>` の 1 行で記録する。`-L`・`-S` は記録せず成功を返す（`ip6tables -L` はシナリオで失敗させられる）。シナリオで指定した 1 つのルールの追加だけを失敗させられる。
    - `dig`: 固定の A／AAAA の応答。シナリオで一時的な失敗にできる。
    - `curl`・`timeout`・`verify_ipv4` の中の `dig`（`+short +time=2 +tries=2 A api.github.com`）: `verify_ipv4` の 4 項目の今の引数の形（上限時間を含む）だけを受け付け、シナリオで届く／届かないを返す。想定外の引数なら rc 99 で失敗する。
    - `ip`: `ip route` の固定出力（デフォルトルートの有無をシナリオで決める）。
    - `date`: 固定の epoch。
    - `ipv6-firewall.py` の差し替え: `prepare`・`refresh`（stdin のドメイン一覧は読み捨てる）・`verify` を受け付け、`<サブコマンド> <引数>` を同じ記録に書く。成功は rc 0。シナリオで `prepare` か `verify` を失敗させられる。
    - `jq`・`awk` は本物を使う。
  - 記録の最後に `rc=<終了コード>` を書く。標準出力と標準エラーは照合しない。
  - 成功シナリオ（記録の全体を期待値ファイルと照合する）:
    - `ipv4-resolver`: IPv6 無効、リゾルバ 1 つ、許可ドメイン 2 つ、GitHub meta は正しい（IPv4 の CIDR を 3 つ以上含む）、検証の 4 項目は全部期待どおり
    - `ipv4-no-resolver`: IPv6 無効、IPv4 のリゾルバ無し
    - `ipv4-no-ip6tables`: IPv6 無効、`ip6tables -L` が失敗する
    - `ipv6-resolver`: `--ipv6`、リゾルバ 1 つ
    - `ipv6-no-resolver`: `--ipv6`、IPv4 のリゾルバ無し
  - 失敗を注入するシナリオ（記録の全体を期待値ファイルと照合する。差し替えのコマンドは、失敗させる呼び出しも記録してから失敗を返すので、記録は `rc=1` の直前がその呼び出しで終わる。失敗の後に処理が進めば、その呼び出しが記録に出て不合格になる）:
    - `rule-add-fails`（GitHub の範囲のうち fixture の最初の CIDR の `iptables -A CLAUDE_EGRESS -d <その CIDR> …` を失敗させる。ループの途中の失敗で止まり、後続の CIDR が記録に出ないことを確かめる）
    - `ip6-drop-fails`（IPv6 無効で `ip6tables -P INPUT DROP` を失敗させる）
    - `resolve-fails`（許可ドメインの 1 つの `dig` を一時的な失敗にする。`refresh_domains` は残りのドメインを処理してから失敗を返すので、記録はそのドメインの後で止まる）
    - `ipv6-prepare-fails`（`--ipv6` で `prepare` を失敗させる）
  - ルールを変える前に止まるべきシナリオ（期待値ファイルを持たない）: `bad-meta`（GitHub meta が不正）、`no-default-route`（デフォルトルートが無い）。判定: `rc=1` で、ルールを変える呼び出しの記録が 1 行も無い（Task 3 でこの 2 つの検査を最初の `iptables -F` より前に動かすため）。今の版ではこの 2 つは途中まで進んでから止まるので、Task 1 の時点では不合格になる。Task 1 ではこの 2 つを「Task 3 で合格させるもの」として、`EXPECT_EARLY_STOP=1` のときだけ判定し、既定では `rc=1` だけを判定する。Task 3 の後は既定を `EXPECT_EARLY_STOP=1` に変える。
  - 検証のシナリオ: `verify-example-reachable`・`verify-github443-blocked`・`verify-anthropic-blocked`・`verify-github80-reachable`（4 項目のうち 1 つだけを期待と逆にする）、`ipv6-verify-fails`（`--ipv6` で helper の `verify` を失敗させる）。記録の全体を期待値ファイルと照合する（`rc=1` で、`rc=` より前は対応する成功シナリオと同じになる）。
  - 期待値ファイルが無いシナリオ（`bad-meta`・`no-default-route` を除く）があれば、テストは失敗する。

- [ ] **Step 2: 今の版で期待値を書き出し、中身を確かめる**

  Run: `UPDATE_EXPECTED=1 bash tests/test-firewall-init-trace.sh; echo rc1=$?; bash tests/test-firewall-init-trace.sh; echo rc2=$?`
  Expected: `rc2=0`。`rule-add-fails.expected`・`ip6-drop-fails.expected` の `rc=1` の直前の行が、それぞれ失敗させた呼び出し。`ipv4-resolver.expected` の 1 行目が `iptables -F`、`rc=` の直前の行が `ip6tables -P OUTPUT DROP`、最終行が `rc=0`。`ipv4-no-ip6tables.expected` に `ip6tables` の行が無く、最終行が `rc=0`。`ipv6-resolver.expected` に `prepare --ports 443,22` と `refresh` と `verify --ports 443,22` がこの順にあり、`rc=` の直前の行が `verify --ports 443,22`、最終行が `rc=0`。

- [ ] **Step 3: テストが今の版を本当に捉えていることを確かめる**

  一時的に `init-firewall.sh` の 404 行と 405 行を入れ替えてテストを走らせ、次に `full_init` の中の GitHub の範囲のループ（443 行の `while` から `done` まで）を `if ! { …; }; then exit 1; fi` で包んだ形にして（ループの中の `set -e` が効かなくなり、`rule-add-fails` で後続の CIDR が記録に出る形の例）走らせ、どちらも元に戻す。

  Run: 入れ替えのたびに `bash tests/test-firewall-init-trace.sh; echo rc=$?`、戻した後に `bash tests/test-firewall-init-trace.sh; echo rc=$?` と `git diff --exit-code init-firewall.sh; echo diff_rc=$?`
  Expected: 入れ替えたときは 2 回とも `rc=1`、戻した後は `rc=0` と `diff_rc=0`。

- [ ] **Step 4: `test-build.sh` に登録して lint**

  `check "ファイアウォール初期化のルールの組み立て（固定入力）" bash "${SCRIPT_DIR}/tests/test-firewall-init-trace.sh"`

  Run: `./lint.sh; echo lint=$?; ./test-build.sh --launcher-only; echo launcher=$?`
  Expected: `lint=0`、`launcher=0`。

- [ ] **Step 5: Commit**

```bash
git add tests/test-firewall-init-trace.sh tests/fixtures/firewall-init-trace test-build.sh
git commit -m "test: #225 書き直す前の init-firewall.sh のルールの組み立てを記録する"
```

### Task 2: 書き直す前のイメージとルール一覧を残す（ホスト）

**Files:** なし（出力は `tmp/225-pre/`）

- [ ] **Step 1: 書き直す前のイメージを作って別のタグを付ける**

  Run: `./test-build.sh --build-only; echo rc=$?; podman tag localhost/claude-test localhost/claude-test:pre-225; podman image exists localhost/claude-test:pre-225; echo exists=$?`
  Expected: `rc=0`、`exists=0`。

- [ ] **Step 2: イメージの中身を記録する（bind mount を付けない）**

  Run（`IMG=localhost/claude-test:pre-225`、`OUT=tmp/225-pre`）:
  ```bash
  mkdir -p "$OUT"
  podman run --rm --user root --entrypoint stat "$IMG" -c '%U:%G %a %n' /workspace /home/node/.claude /etc/sudoers.d/node-firewall > "$OUT/stat.txt"
  podman run --rm --user root --entrypoint cat "$IMG" /etc/sudoers.d/node-firewall /etc/c3c/github-meta.json > "$OUT/files.txt"
  ```
  Expected: 2 つのファイルができ、`stat.txt` が 3 行。

- [ ] **Step 3: ルール一覧を記録する**

  Run:
  ```bash
  podman run --rm --user root --cap-add NET_ADMIN --cap-add NET_RAW --entrypoint bash "$IMG" -c '/usr/local/bin/init-firewall.sh >/dev/null && iptables-save && echo ===== && ip6tables-save' > "$OUT/rules.txt"; echo rc=$?
  ```
  Expected: `rc=0`。`rules.txt` に `:CLAUDE_EGRESS` と `-A OUTPUT -j REJECT --reject-with icmp-admin-prohibited` がある。

  **REQUIRED SUB-SKILL:** Use superpowers:systematic-debugging（この起動で init-firewall.sh が失敗したら、その場で原因を調べる。entrypoint を通らない起動なので、足りない前提があれば Step 3 のコマンドを直し、直した形を台帳に書いて Task 7 でも同じ形を使う）

- [ ] **Step 4: Compose の設定を記録する**

  Run: `podman compose -f compose.yml config > "$OUT/compose-config.txt" 2>/dev/null; echo rc=$?`（`lint.sh` 183 行と同じく、環境変数を足さずに実行する。Task 5 でも同じシェルの環境で行う）
  Expected: `rc=0`。

### Task 3: `init-firewall.sh` を組み直す

**Files:**
- Modify: `init-firewall.sh`（冒頭のコメント、`verify_ipv4()`、`full_init()`。c3c の作者の関数は変えない）

**Interfaces:**
- Consumes: Task 1 の `tests/test-firewall-init-trace.sh` と期待値（変えない）
- Produces: `full_init()` と `verify_ipv4()` の名前を残す（`case "$MODE"` と既存のテストが呼ぶ）。`full_init()` の補助として新しく作る関数の名前は実装者が決める。

- [ ] **Step 1: 組み立てを決めて、台帳に書く**

  `full_init()` を、処理のまとまりごとの関数に分ける案を決め、executing-plans の台帳に 5 行以内で書く。次の 2 つの時機の変更は必ず行う（spec の「ルールを変えない処理の時機」）:
  - GitHub meta のスナップショットの読み込みと検査を、最初の `iptables -F` より前に行う。
  - デフォルトルートからのホスト IP の検出を、最初の `iptables -F` より前に行う。

  IPv6 helper の `prepare` を呼ぶ位置と、`disable_ipv6_fallback` の位置は変えない。守ること: DNS の許可より前にネットワークを使わない、成功するときのルールを変える呼び出しの列が同じ、失敗のときは rc 1 で止まる。

- [ ] **Step 2: 書き直す**

  - 冒頭のコメントを、c3c のファイアウォールが何をするかの説明として書き直す（「移植」と Anthropic 版との差分の列挙をやめる）。
  - `full_init()` を Step 1 の案で組み直す。443 行の GitHub の範囲のループの書き方も変える。
  - `verify_ipv4()` は本体の中の組み立てを変える（Global Constraints の呼び出しの形は保つ）。4 項目、それぞれの上限時間（example.com は接続 5 秒・全体 10 秒、api.github.com:443 は `dig` の `+time=2 +tries=2` と `timeout 10`、api.anthropic.com は接続 10 秒・全体 20 秒・再試行なし、api.github.com:80 は `timeout 5`）、失敗時の exit 1 は変えない。

- [ ] **Step 3: 回帰テストと既存のテスト**

  **REQUIRED SUB-SKILL:** Use superpowers:systematic-debugging（列が一致しないときは、期待値を直さず、その場で原因を調べて書き直しの側を直す）

  Run: `./lint.sh; echo lint=$?; EXPECT_EARLY_STOP=1 bash tests/test-firewall-init-trace.sh; echo trace=$?; ./test-build.sh --launcher-only; echo launcher=$?; git diff --exit-code tests/fixtures/; echo fixtures_diff=$?`
  Expected: すべて 0。

- [ ] **Step 3b: テストの既定を早い停止の判定に変える**

  `tests/test-firewall-init-trace.sh` の `EXPECT_EARLY_STOP` の既定を 1 にする（期待値ファイルは変えない）。

  Run: `bash tests/test-firewall-init-trace.sh; echo trace=$?`
  Expected: `trace=0`。

- [ ] **Step 4: Commit**

```bash
git add init-firewall.sh tests/test-firewall-init-trace.sh
git commit -m "refactor: #225 init-firewall.sh の初期化と自己検証を c3c の仕様から組み直す"
```

### Task 4: `c3c` の引数解析を書き直す

**Files:**
- Modify: `c3c`（8〜11 行の初期化、130〜201 行の引数解析、2944 行）

- [ ] **Step 1: 書き直す**

  README「使い方」、`usage()`、`set_agent_option()` の規則を変えずに、引数解析の組み立てを書き直す。守ること: 最初の位置引数の `claude`／`codex` だけがサブコマンド、`--` 以降はすべて位置引数、`--agent` は値の欠落と `--agent=` の両方、`--read-only` の二重指定は exit 2、未知のオプションは同じ文面で exit 2、`-h` と `--help` は exit 0。解析の後に `POSITIONAL_ARGS`・`C3C_SUBCOMMAND`・`BUILD`・`CLEAN`・`CHECK`・`CLEAN_MISSING`・`READ_ONLY`・`READ_ONLY_SET` が今と同じ値になること。

- [ ] **Step 2: テスト**

  Run: `./lint.sh; echo lint=$?; ./test-build.sh --launcher-only; echo launcher=$?; ./c3c -h >/dev/null; echo h=$?`
  Expected: すべて 0（`tests/test_c3c_launch.py` の parser・`--`・サブコマンドの検査を含む）。

- [ ] **Step 3: Commit**

```bash
git add c3c
git commit -m "refactor: #225 c3c の引数解析を書き直す"
```

### Task 5: `Dockerfile.claude` と `compose.yml` を書き直す

**Files:**
- Modify: `Dockerfile.claude`（180〜181 行、345〜346 行、周りのコメント）
- Modify: `compose.yml`（37〜39 行のコメントアウトされた `profiles` を消す）

- [ ] **Step 1: 書き直す**

  - 180〜181 行: `/workspace` と `/home/node/.claude` を node:node で作る書き方を変える。
  - 345〜346 行: sudoers の中身（`node ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh`）、ファイル名、mode 0440、所有者 root は変えず、書き込み方を変える。
  - `compose.yml`: 37〜39 行を消す。キーと値は変えない。

- [ ] **Step 2: テストと比較**

  Run: `./lint.sh; echo lint=$?; ./test-build.sh --validator-only; echo v=$?; ./test-build.sh --build-only; echo b=$?; ./test-build.sh --config-ro-only; echo c=$?`、続けて Task 2 の Step 2 と Step 4 を `IMG=localhost/claude-test`、`OUT=tmp/225-post` で行い、`diff tmp/225-pre/stat.txt tmp/225-post/stat.txt` と `diff tmp/225-pre/compose-config.txt tmp/225-post/compose-config.txt`
  Expected: すべて rc 0、2 つの `diff` に差分なし。`files.txt` は sudoers の部分が同じ（GitHub meta の部分はビルドのたびに取り直すので、ここでは比べない）。

- [ ] **Step 3: Commit**

```bash
git add Dockerfile.claude compose.yml
git commit -m "refactor: #225 Dockerfile.claude と compose.yml のフォーク元の書き方を書き直す"
```

### Task 6: 表示の整理

**Files:**
- Modify: `LICENSE`（「Upstream Attribution」の節と MIT の全文を外し、注記を足す）
- Modify: `README.md`（「ライセンス」節、588 行の `init-firewall.sh` の説明）

- [ ] **Step 1: 書き直す**

  - `LICENSE`: 冒頭の 1 文の後に注記を置き、「Upstream Attribution」と MIT の全文を外す。GPL-3.0 の本文は 1 文字も変えない。注記の趣旨: このリポジトリの git の履歴の初期の版には、sethjensen1/claude-container（MIT）のコードと、Anthropic の devcontainer の例を元にしたコードが含まれる。現在の版では書き直されている。
  - README「ライセンス」節: 同じ事実を日本語で書く。
  - README 588 行: 「Anthropic 公式 devcontainer の同名スクリプトの移植」をやめ、c3c のファイアウォールとしての説明にする。
  - README 冒頭の「フォークした」と `AGENTS.md` は変えない。

- [ ] **Step 2: 確かめる**

  Run:
  ```bash
  ./lint.sh; echo lint=$?
  diff <(git show HEAD:LICENSE | sed -n '/^## GNU General Public License v3.0/,$p') <(sed -n '/^## GNU General Public License v3.0/,$p' LICENSE); echo gpl_diff=$?
  grep -n "移植" README.md init-firewall.sh; grep -n "MIT" README.md LICENSE
  ```
  Expected: `lint=0`、`gpl_diff=0`。`移植` は README 749 行（Docker への移植の話で、由来の記述ではない）だけ。`MIT` は `LICENSE` の注記と README のライセンス節だけ。

- [ ] **Step 3: Commit**

```bash
git add LICENSE README.md
git commit -m "docs: #225 LICENSE と README の帰属の表示を整理する"
```

### Task 7: 実コンテナでの一致、起動、一致行の再集計

**REQUIRED SUB-SKILL:** Use superpowers:systematic-debugging（想定外の差分が出たら、その場で原因を調べる）

**Files:** なし（出力は `tmp/225-post/`）

- [ ] **Step 1: 書き直した後のルール一覧を記録して比べる**

  Task 2 の Step 3 を `IMG=localhost/claude-test`、`OUT=tmp/225-post` で行う。比べる前に、両方の `rules.txt` を次のように正規化する: `#` で始まる行を除く、カウンタ（`[n:m]`）を `[0:0]` にする、`--comment` に `gen=` を含む行の IP（`-d <IP>/32`）を `-d IP/32` に、`gen=<数字>` を `gen=N` にしたうえで、連続する同じ行を 1 行にまとめる（CDN が返す IP の数は問い合わせごとに変わるため）。

  Run: `diff <正規化した pre> <正規化した post>`
  Expected: 差分なし。差分が出たら、まず (a) 両方の `files.txt` の GitHub meta の違い（ビルドのたびに取り直す）、(b) 許可ドメインの解決の揺れを疑う。(a) なら、GitHub の CIDR の行を除いて比べ直し、除いた理由を PR 本文に書く。

- [ ] **Step 2: 既存の実コンテナのテスト**

  Run: `bash tests/test-runtime.sh --image localhost/claude-test; echo runtime=$?; ./test-build.sh; echo full=$?`
  Expected: どちらも 0。実 IPv6 の確認をしなければ `not run` と理由を書く。

- [ ] **Step 3: 実起動**

  c3c の checkout を作業ディレクトリにして `./c3c claude -b .` と `./c3c codex .` を起動し、起動時の自己検証の「検証 OK」が 4 行出ること、`/exit` で終われることを確かめる（持ち主と一緒に行う）。旧イメージの利用側でドリフトの WARNING が出るのは想定内。

- [ ] **Step 4: 一致行の再集計（計画者が行う）**

  実装者は元ファイルを開けないので、ここで handover を書いて止まり、計画者のセッション（または独立レビューの側）に渡す。計画者は「書き直す行の一覧」と同じ 2 つの方法で集計し直す（元ファイルはリポジトリの外に置く）。

  Expected: (1) blame でフォーク元の作者の行は、空行と「残」の行だけ。(2) 元ファイルと一致する行は、「残」の行と、12 文字未満の定型の構文だけ。結果を PR 本文に書く。Task 8 は、この結果が出てから始める。

### Task 8: PR 前の二重レビューと PR

- [ ] **Step 1: PR 前の二重レビュー（区分は境界）**

  claude-review skill と codex-review skill の手順で、作成に関わっていない Claude と Codex（`gpt-6.1-sol`）に、spec・計画・`main..HEAD` の差分・Task 7 の結果を渡す。

- [ ] **Step 2: 指摘の反映**

  **REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review

  Critical・Important を直し、確認限定巡を終える。直したら Task 3〜7 のうち関係する検証をやり直す。

- [ ] **Step 3: push と PR（持ち主の確認の後）**

  **REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:finishing-a-development-branch

  PR 本文: 区分（境界）、PR 前の二重レビューの判定と未対応の Minor、Task 7 の結果（一致行の再集計を含む）、`not run` の項目と理由、README 749 行の「移植」を残した理由（Docker への移植の話で由来の記述ではない）、`Closes #225`。両レビュアーの全文を PR コメントに投稿する。PR 後の二重レビューは handover で別のセッションへ渡す。

---

## 計画レビューの記録

- Self-Review: スキルの指定 1 件（Global Constraints に test-driven-development）を追加
- Claude（claude-opus-5-5、session `0a9921c0-d02b-4411-a5d0-09b4dffe3321`、所要 274 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/bk5j3xzdr.output`
  - C1 失敗シナリオの列の一致と、spec が求める時機の変更がぶつかる → 採用（時機の変更を 2 つに決め、失敗シナリオは prefix と rc で判定）
  - I1 `verify_ipv4` を名前だけ残しても既存のテストが壊れる → 採用（本体の中で完結、呼び出しの形を保つ）
  - I2 一致行の一覧と blame がずれる → 採用（blame の 49 行を行番号で列挙し、書／残を付けた）
  - I3 行番号のずれ → 採用（`c3c` は 8〜11・130〜201）
  - I4 実コンテナの比較が書き直しと関係なく差分を出す → 採用（meta の保存と、連続する同じ行をまとめる正規化）
  - I5 固定入力の穴（解決の失敗、`ip6tables -L` の失敗、helper の `refresh`、上限時間） → 採用
  - I6 LICENSE の確認で GPL の本文を判断できない → 採用（GPL 節の `diff`）
  - I7 Task 2・5 の手順が具体的でない → 採用（コマンドを逐語にした）
  - I8 公開の置き場へ移すときにホストのパスが残る → 採用（`~/` のパスを除いた）
  - M1 profiles は 37〜39 行 → 採用。M2 再集計の担当 → 採用。M3 並走は未 push で走らない → 公開の計画には書かず、PR 本文で扱う。M4 テストの安全（固定パスの残り、root、locale） → 採用。M5 README 749 行 → 採用（PR 本文に書く）。M6 Expected の書き方 → 採用。M7 Task 3 Step 3 の扱い → 採用（systematic-debugging）
- Codex（gpt-6.1-sol、所要 212 秒）: 修正後に渡せる。生の出力 `<scratchpad>/tasks/b9hta32or.output`
  - I1 fail-closed の失敗が固定入力に無い（`if !` で `set -e` が効かない反例つき） → 採用（失敗の注入 5 種と、条件の中から呼ばない制約）
  - I2 イメージの中身の検査が bind mount を測る → 採用（bind mount を付けない `podman run`）
  - I3 ドメインのルールの件数の比較では足りない → 採用（IP と gen を伏せて全体を比べる）
  - I4 helper の `refresh` が差し替えに無い → 採用
  - I5 GPL の本文の確認が足りない → 採用（Claude I6 と同じ）
  - I6 verification-before-completion の位置が早い → 採用（Task 8 Step 3 へ移した）
  - M1 計画の最終の置き場 → 採用（承認の直後に `docs/superpowers/plans/` へ置く）。M2 `verify_ipv4` の抽出 → 採用（Claude I1 と同じ）。M3 確認のコマンドの rc と `git stash` → 採用（rc を個別に出し、compose の比較は Task 2 で保存）
- 確認限定巡 1: Codex（I1〜I6、所要 32 秒）→ I2〜I6 は解消、I1 は一部未解消（IPv6 の DROP の失敗の注入が無い、prefix の判定では失敗の後に進んでも通りうる）。生の出力 `<scratchpad>/tasks/bou21h07c.output`
  - I1 の残り → 採用（失敗を注入したシナリオは期待値ファイルと全体を照合して、失敗した呼び出しで記録が終わることを確かめる。`ip6-drop-fails` を追加。meta とホスト IP の失敗は「ルールを 1 つも変えずに止まる」で判定し、Task 3 でその判定を既定にする）
- 確認限定巡 1: Claude（C1・I1〜I8、所要 41 秒）→ すべて解消、実装に渡せる。ただし Codex の I1 の残りを直す前の版を読んだ。残った軽い 2 点（`verify_ipv4` の `dig` の引数の照合、`ipv6-resolver` の `rc=0`）→ 採用。生の出力 `<scratchpad>/tasks/b9yeoy2zq.output`
- 確認限定巡 2: Codex（I1 の残り、所要 37 秒）→ 解消、実装に渡せる。生の出力 `<scratchpad>/tasks/b1hoia95i.output`
- 確認限定巡 2: Claude（変更後の C1・I5、所要 33 秒）→ C1 は解消。I5 (a) が未解消（Task 1 Step 3 で包むループと `rule-add-fails` の注入先が噛み合わず、包んでも不合格にならない）→ 採用（注入先を GitHub の範囲の最初の CIDR にした）。生の出力 `<scratchpad>/tasks/banh1tbmw.output`
- 確認限定巡 3: Claude（I5 (a)、所要 15 秒）→ 解消、実装に渡せる。前提として fixture の CIDR を 2 つ以上と挙げた → 採用（3 つ以上と明記）。生の出力 `<scratchpad>/tasks/bb63u34dv.output`
- grok と argon の並走: not run（対象の commit が GitHub に無い。計画の写しを送る前提を満たさない）

区分: 境界 — `init-firewall.sh` はエグレス制限の中心で `docs/development-invariants.md` の不変条件に触れ、`LICENSE` の変更は対外的で取り消しにくい。
推奨実装: Opus — 判定順の 3（`full_init()` の分け方を実装中に決める設計判断が残る）で Claude になり、セキュリティ境界を含むので Opus を推す。Task 2・5・7 はホストの podman が要るので、ホストの Claude のセッションで行う。Sonnet を推さないのは、ルールの順番と fail-closed を保ったまま構造を組み直す判断が中心で、誤ると境界が黙って緩むため。Codex（判定順の 4 のホスト限定）は、3 が先に当たるので推さない。実行方法は executing-plans（Task が順に依存し、数も 8 と少ない）。
