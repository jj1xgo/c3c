# 溜まった Issue のコード側の片付け（#159・#112・#126・#132）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

## 目的と状態

レビューで出た nit を束ねた Issue（#112・#126・#132）と、小さなバグ #159 を、1 本の PR で閉じる。止まり方を分かりやすくすること、検査の抜けを埋めること、文書を正確にすることが目的。止まる条件が増えるのは、#159（`.claude.json` の欠落と型違い）と #112-2（実体名のコロン・制御文字）だけ。基準は main `151ec20`（v14.1.1）。文書だけで閉じる Issue は、別の計画 `2026-09-25-docs-issue-sweep.md` で扱う。

持ち主の判断（2026-09-25）:

- #159: 欠落と型違いを、compose より前に ERROR で止めるだけにする。`{}` の自動作成はしない。
- #112-1: `guard_agents_dir()` の解決を `cd -P`（物理解決）にして、`-d`（カーネル）と同じ結果にする。`..` はこれまでどおり受け付ける（初回の計画では `..` を拒否する案だったが、互換性を壊すので計画レビューの後に持ち主が変えた）。repo 全体を `cd -P` にはしない。

持ち主が実装者を指定するまで、製品ファイルは編集しない。着手前に、`docs/development-invariants.md` の該当節（`c3c`・`lint.sh` の入力検証とガード、24 行目の呼び出し列、36 行目の `AGENTS_DIR`、54 行目の lint の compose 検査、56 行目の `prepare_claude_config_ro`）を読む。

## 事実（2026-09-25 に main `151ec20` で確かめたこと）

- **#159:**
  - `c3c` には `.claude.json` の検査が無い（`grep -n 'claude\.json' c3c` は 0 件）。
  - `compose.yml:55` は `${CLAUDE_CONFIG_DIR:-~}/.claude.json` を短い書式で bind しているので、source が無いと podman が空のディレクトリを作る。イメージ（`Dockerfile.claude`）には `.claude.json` を作る処理が無い。
  - #159 の本文に、`c3c codex` の検査用コンテナが `crun: mount ... Not a directory` の rc=126 で止まる再現ログがある。つまり、欠落した構成は今も Codex 経路で起動できていない。Claude 経路で同じ失敗になるかは、実測していない。
- **ガードの呼び出し列:**
  - `--check`（`c3c:2253-2268`）は、`guard_ipv6` の直後に `prepare_claude_config_ro` と `guard_plugins_alias` が続く。
  - 通常起動（`c3c:2569` から）は、`guard_ipv6`（2582 行目）の後に `guard_asset_drift` と `check_mcp_approval`（2591 行目、TTY で確認する）が入り、`prepare_claude_config_ro` は 2600 行目。
  - `CLAUDE_CONFIG_DIR` の基点の解決（`~` の展開、相対パスの拒否、`cd … && pwd -P`）は、`prepare_claude_config_ro` の中（`c3c:1387-1406`）にある。
- **`guard_fail` の出力:** `[FAIL]` は付けない（`c3c:45-52`）。`ERROR: …` をそのまま出し、`--check` では集計して `→ 結果: FAIL` と rc≠0 にする。
- **#132-1:** 型違いの文言は `c3c:1363`（ディレクトリ）と `c3c:1365`（ファイル）で、どの名前でも同じ。
- **#132-2:** `test-build.sh:1684` の `G1 .git が gitfile` は、通常起動と `--check` の両方で、rc≠0・ERROR・名前の一致・compose を呼ばないことを見ている（`test-build.sh:1668-1675`）。Issue の項目 2 は、これで解消済みとして扱う。
- **#132-3:** README（674 行目）の限界 (8) に、`[ -d .git ]` だけで判定するツールについての注記が無い。
- **#132-4:** `CONFIG_RO_PROBE`（`test-build.sh:388-416`）は、ディレクトリの中身への作成・追記・削除は検査するが、マウントポイント自体の `mv` と `rmdir` は検査しない。codex plugins の probe（495 行目）には `rmdir` がある。
- **#112-1:** `guard_agents_dir()`（`c3c:1658-1688`）は、`cd "$agents_path" && pwd -P` で解決している。bash は `..` を論理的に畳んでから移動するので、`-d` の物理解決とずれる（Issue の再現: `/var/run/../tmp` が `/var/tmp` になる）。
- **#112-2:** `guard_shared_home_alias`（`SHARED_MOUNT` の `pwd -P`、1642 行目）と `guard_agents_dir` は、`pwd -P` の結果（実体）に対してコロンと制御文字を検査し直していない。コマンド置換は末尾の改行を落とす。
  - `SHARED_MOUNT_HOME_ALIAS=0` のときは、`guard_shared_mount`（1583-1591 行目）が実体解決もコロンの検査もしない。これは今回の範囲外とする（compose の短い書式 `${SHARED_MOUNT}:/shared` への影響は、Issue の由来どおり operator 入力に依存する）。
- **#112-3:** `instruction_paths_overlap()`（`c3c:1607`）は、`/` を含む比較で重なりを見落とす。`guard_codex_host_plugins` は `${x%/}` で回避している（1709 行目）。`guard_agents_dir` は回避していない。
- **#112-4:** `lint.sh:247` の needle は、アンカーの無い部分一致。既存の `compose_mount_is_ro`（`lint.sh:72` から）は、短い書式と long syntax の両方を、target の完全一致で扱える。
- **#112-5:** README 182 行目の `SHARED_MOUNT_HOME_ALIAS` の行に、空文字の扱い（実装は `${…:-0}` で 0 扱い）が無い。
- **#126-1・2:** `docs/development-invariants.md` 24 行目は、「ディレクトリ解決はモードごとの前段処理で、`guard_*` の共用の対象外」と書いていない。`valid_path`（`project-images.py:23`）が `--check --clean-missing` の前段のガードを兼ねていることも書いていない。
- **#126-3:**
  - #122 のテスト（`test-build.sh:960` 付近のループ）は、`--clean .`・`--clean ..`・`claude .`・`--check .` を、PWD の none と stale の組み合わせで試す 8 ケース。
  - 2026-09-25 に bash で実測した。削除済みの cwd から `cd -- ../sibling` を実行すると、PWD が古い値でも無くても成功し、`pwd -L` は相対の `../sibling` を返した。したがって、今の `resolve_project_directory()` は「絶対パスでない」として止まる見込み。
- **#126-4:**
  - `--check .`（削除済みの cwd）では、FAIL の行が 2 つ出る。1 つは `project-images.py:214` の `InspectionError` を `:314` で出すヘルパーの行、もう 1 つは `check_one_project()` の行。
  - `run_check_mode` は、すべての引数をまとめて 1 回だけヘルパーに渡し（`c3c:2422-2437`）、`--clean-missing` ではヘルパーの `result.json` で targets を置き換える（2440-2455 行目）。

## Task 1: #159 `.claude.json` の欠落と型違いを compose より前に止める

**Files:** `c3c`、`test-build.sh`、`README.md`、`docs/development-invariants.md`

- [ ] 先に、今の挙動を記録する。
  - 既存のイメージがあれば、`.claude.json` を欠いた仮の基点で、Claude 経路と Codex 経路がそれぞれどこで失敗するかを見る（TTY を付けない。`c3c claude -b` で TUI を起動しない）。
  - イメージが無ければ not run とし、Codex 経路は #159 の再現ログを根拠にする。
- [ ] 基点の解決を、副作用の無い共通の関数（例: `resolve_claude_config_base`）に切り出す。
  - 中身は `prepare_claude_config_ro` の 1386-1410 行目と同じ規則（`~` の展開、相対パスの拒否、`-d`、`cd … && pwd -P`）。
  - 関数は 2 つの値を返す（グローバル変数に入れる、など）。1 つは実体に解決した基点、もう 1 つは plugin の別名用の「`~` 展開済みで実体は未解決」の綴り（今の `host_base`）。
  - 関数は `guard_fail` も export もしない。検証に失敗したら、失敗の種類を終了コードで返す（相対パス、見つからない、入れない、の 3 種）。`prepare_claude_config_ro` はこれを見て、今の 3 つの文言（1395・1398・1401 行目）を出し分ける。
  - `CLAUDE_CONFIG_DIR` の export と `CLAUDE_CONFIG_HOST_BASE` の代入、それに検証失敗時の `guard_fail` の文言は、今の場所（`prepare_claude_config_ro`）に残す。これにより、既存の文言と plugin の別名の判定（`guard_plugins_alias`）を変えない。
  - `prepare_claude_config_ro` と新しいガードの両方がこの関数を使い、同じ基点を見るようにする。解決は `--check` と通常起動で同じ結果になること。
  - テスト: `CLAUDE_CONFIG_DIR` に symlink と `..` を組み合わせた指定（例: `<root>/link/../cfg`。`link` は別の場所を指す）を使う。そのうえで、新しいガードが見る `.claude.json`、`prepare_claude_config_ro` が作る 12 項目の場所、compose に渡す `CLAUDE_CONFIG_DIR` が、同じ実体の基点を指すことを確かめる。
    - 物理解決と論理解決で、`.claude.json` の有無が食い違うように配置する。
    - 期待する基点は論理側（今の規則。`cd` の後の `pwd -P`）。`CLAUDE_CONFIG_DIR` は `cd -P` にしない。`cd -P` にするのは #112-1 の `AGENTS_DIR` だけで、取り違えないこと。`-d` は元の綴りを物理的に解決するので、フィクスチャには物理側と論理側の両方にディレクトリを作る。
    - plugin の別名の綴り（`CLAUDE_CONFIG_HOST_BASE`）が今と同じ値になることも確かめる。
- [ ] `guard_claude_json()` を新設し、両モードの呼び出し列で `guard_ipv6` の直後に置く。通常起動では、`guard_asset_drift` と `check_mcp_approval` より前になる。
  - 基点が解決できない（相対パス、存在しない等）ときは、何も出さずに `return 0` し、診断は今までどおり `prepare_claude_config_ro` に任せる。これで、既存の `CLAUDE_CONFIG_DIR=relative/dir` のテスト（`test-build.sh:1626`）の文言を変えない。
  - 欠落: ERROR で止める。ホストで Claude Code に一度ログインすれば作られること、または中身が `{}` のファイルを置けばよいことを案内する。
  - 壊れた symlink（`-L` かつ `! -e`）: 専用の文言で止める。リンク先を直すか置き直すよう案内する。
  - ディレクトリ: ERROR で止める。podman が以前作った空のディレクトリかもしれないので、中身を確かめてから `rmdir` するよう案内する。
  - 通常ファイル以外（FIFO など）: ERROR で止める。
  - 通常ファイルへの symlink: 通す。ホストの dotfile 管理で symlink にしている構成を壊さないため。このファイルは `:ro` 保護の 12 項目と違い、もともと rw の共有なので、symlink を拒否する理由が無い。
- [ ] テスト（`test-build.sh --launcher-only`）
  - 失敗の 4 ケース（欠落・壊れた symlink・ディレクトリ・FIFO）: 通常起動の rc≠0 と文言、compose を呼んでいないこと、`--check` の ERROR 行と `→ 結果: FAIL` と rc≠0。
    - compose を呼んでいないことは、compose 専用の記録（既存のテストが使う compose の引数記録）で見る。`guard_asset_drift` が podman を呼ぶので、podman の引数記録の有無では判定できない。
  - 成功の 2 ケース（通常ファイル、通常ファイルへの symlink）: compose に到達し、このガードの ERROR が出ないこと。
  - Codex 経路（`c3c codex`）でも、検査用コンテナ（preflight）より前に止まること。
- [ ] 既存のテストのフィクスチャに、`{}` の `.claude.json` を足す。対象は、基点（HOME か `CLAUDE_CONFIG_DIR`）を作るすべての箇所。
  - 少なくとも次を含む: `config_ro_fixture_setup()`（`test-build.sh:673`）、`run_launcher CLAUDE_CONFIG_DIR=...` を使う箇所（1340・1634・1663-1665・1786・1802・1809・1821-1823 行目付近）、env の非混入テスト（2310-2343 行目。`--launcher-only` の外）。
  - 否定側のテスト（G 系など、ERROR を期待するもの）には、「`.claude.json` の ERROR 文言を含まない」を足す。新しいガードの ERROR で、本来の検査に届かないまま通ることを防ぐため。
  - Python 側（`tests/test_c3c_launch.py`、`tests/test_codex_launch.py`）は、既に `{}` を作っているので変えない。
- [ ] README「前提」節と `--check` の検査項目にこの検査を足す。不変条件 24 行目の呼び出し列の説明と、56 行目の `prepare_claude_config_ro` との順序の説明を更新する。

**Expected:** 新しい 6 ケースと Codex 経路のケースが PASS。既存のテストが FAIL=0 のまま。

## Task 2: #112 の 1〜5

**Files:** `c3c`、`lint.sh`、`tests/test-lint-compose-checks.sh`、`test-build.sh`、`README.md`、`docs/development-invariants.md`

- [ ] 1: `guard_agents_dir()` の解決を `CDPATH='' cd -P -- "$agents_path"` にする。
  - `..` はこれまでどおり受け付け、`-d` と同じ実体になる。
  - テスト: symlink と `..` を組み合わせた指定（例: `<root>/link/../x`。`link` は別の場所を指す）で、export される `AGENTS_DIR` が物理解決の結果になること。
- [ ] 2: `guard_shared_home_alias` の `SHARED_MOUNT` と `guard_agents_dir` の実体解決を、末尾に番兵を付ける方式にする。
  - 方式: `run_check_mode`（2427 行目の `$(cd -- "$d" && printf '%s.' "$PWD")`）と同じく、コマンド置換の中で `$PWD` に番兵を付ける。例: `x=$(CDPATH='' cd -P -- "$p" && printf '%s.' "$PWD") && x=${x%.}`（`cd -P` の後の `$PWD` は物理パス）。`printf '%s.' "$(pwd -P)"` は内側の置換で改行が落ちるので使わない。
  - その後、実体にコロンか制御文字があれば ERROR で止める。
  - テスト:
    - 実体名にコロンを含むディレクトリへの symlink。
    - 実体名の末尾に改行があるディレクトリへの symlink。改行を落とした名前の同名ディレクトリも作っておき、そちらへ黙って流れないことを確かめる。
- [ ] 3: `guard_agents_dir()` の重なりの比較で、`guard_codex_host_plugins` と同じく末尾の `/` を除いてから比べる。
  - テスト: `AGENTS_DIR=/` と、`/` を指す symlink の両方で、rw の source と重なるという WARNING が出ること。拒否にはしない（rc 0）。
- [ ] 4: `lint.sh:247` の needle のうちマウントに当たるもの（plugins-alias・shared-home・shared-host・`.agents`・codex の cache）を、`compose_mount_is_ro <target>` による完全一致の検査に置き換える。
  - IPv6 の `fe80::1` はマウントではないので、`compose.ipv6.yml` の該当キーの行に、行頭と行末のアンカーを付けて照合する。
  - `tests/test-lint-compose-checks.sh` に、target を `/home/node/.agents-x` に変えた場合に赤になるケースと、短い書式と long syntax の両方のケースを足す。
- [ ] 5: README 182 行目の `SHARED_MOUNT_HOME_ALIAS` の説明を、「未指定・空・`0` は無効。`0`/`1` 以外は起動と `--check` で拒否」の形にする（`CLAUDE_CONTAINER_IPV6` の行と同じ書き方）。
- [ ] README の `AGENTS_DIR` の行と、不変条件 36 行目に、物理解決と、実体の検査を足したことを反映する。

**Expected:** 追加のテストが PASS。`./lint.sh` が rc 0。

## Task 3: #126 の 1〜4

**Files:** `docs/development-invariants.md`、`test-build.sh`、`c3c`

- [ ] 1: 不変条件 24 行目の後に、次の文を足す。「ディレクトリ解決（`cd -- && pwd -L` と絶対パスの検査）は、モードごとの前段処理で、`guard_*` の共用の対象外。同じ述語を足すときは、通常起動の `resolve_project_directory()` と、`--check` の `check_one_project()` の両方に足す」。
- [ ] 2: 同じ節に、`project-images.py` の `valid_path` の絶対パスの要件が、`--check --clean-missing` の前段のガードを兼ねていることを書く。
- [ ] 3: #122 のループに、次の 3 入力 × PWD の 2 条件（none、stale）= 6 組を足す。
  - `--check ..`
  - `--check --clean-missing .`
  - `--clean ../sibling`: 削除する cwd（`$root/gone`）の兄弟として `$root/sibling` を作っておく。
  - 期待値は 6 組とも「止まる」: rmi/rm/prune を呼ばない、台帳が変わらない、絶対パスを求める案内の文言がある。
  - 実装を変える前にテストを書いて走らせる。止まらない組があれば、それは #122 と同じ型の欠陥なので、直す前に計画者（持ち主）へ返す。
- [ ] 4: `--check .` の FAIL を 1 行にする。
  - `run_check_mode` がヘルパーに渡す `--project=` の一覧から、削除済みの cwd のせいで絶対パスに解決できない引数（`.`・`..` など）だけを外す。
  - 残りの対象があればヘルパーを呼ぶ。1 件も残らず、台帳の診断（引数なし）でもなければ、ヘルパーを呼ばない。
  - 外した対象の FAIL は、`check_one_project()` の 1 行に任せる。
  - `--clean-missing` で `result.json` が無い場合に、「清掃診断の結果を読み取れません」の FAIL が新たに出ないようにする。
  - 外した対象は、別の配列に保持する。`--clean-missing` で `targets` を `result.json` の結果に置き換えた後に、その配列を `targets` へ戻し、`check_one_project()` が対象ごとに FAIL を 1 行出すようにする。
    - `--check --clean-missing . <絶対パス>` で、`.` が置き換えで消えないようにするため。
  - 回帰テスト:
    - 削除済みの cwd から `--check <実在する絶対パス>` が今までどおり診断されること。
    - 引数なしの台帳の診断。
    - `--check . <実在する絶対パス>` の混在で、絶対パスの方の診断が消えないこと。
    - `--check .` の出力の FAIL 行が 1 行で、サマリの FAIL 数と rc が今と同じこと。
    - `--check --clean-missing . <実在する絶対パス>` で、`.` の FAIL が 1 行出ること。絶対パスの方の診断と清掃の判定は今と同じで、rc≠0 になること。

**Expected:** 追加の 6 組と回帰のテストが PASS。

## Task 4: #132 の 1〜4

**Files:** `c3c`、`test-build.sh`、`README.md`

- [ ] 1: `validate_claude_config_ro_path` で、`path` の basename が `.git` で型違いのときだけ、文言に次の文を足す。「`~/.claude` が worktree か submodule だと `.git` はファイル（gitfile）になる。README「セキュリティモデル」節の限界 (8) を参照」。
- [ ] 2: G1 の検査に、1 の文言が出ることを加える。
- [ ] 3: 限界 (8) に 1 文足す。「空の `.git` は git の通常の探索では無視されるが、`[ -d .git ]` だけで判定する素朴なスクリプトやエディタ拡張は、`~/.claude` をリポジトリと誤認しうる」。
- [ ] 4: `CONFIG_RO_PROBE` のディレクトリのループに、マウントポイント自体の `mv "$d" "$d.moved"` と `rmdir "$d"` を足す。期待は EBUSY か EROFS。
  - 既存の判定（EROFS か EBUSY 以外の理由で失敗したら FAIL）は緩めない。
  - `rmdir` が ENOTEMPTY などで失敗して想定と違ったら、判定を緩めずにフィクスチャの作り方に戻り、計画者に返す。
  - `mv` が成功してしまった場合（漏れ）は、FAIL を記録したうえで元に戻す。2 回目の probe（530 行目、同じ root）を崩さないため。
  - 実 Podman が要る（`--config-ro-only`）。

**Expected:** `./test-build.sh --config-ro-only` が PASS（実 Podman）。launcher のテストが PASS。

## Task 5: 検証

- [ ] `./lint.sh` が rc 0。
- [ ] 引数なしの `./test-build.sh`（完全版。env の非混入テストを含む）が FAIL=0。時間の都合で分けるなら、`--launcher-only`・`--config-ro-only` と、2310 行目付近の節を含む残りを、両方とも実行する。
- [ ] README「変更後の確認」節のうち、今回の変更箇所に当たるもの。実行できなかったものは、理由とともに not run と書く。
- [ ] ホストの実環境で `./c3c --check <実プロジェクト>` を実行し、`.claude.json` のある通常の構成で、新しいガードが FAIL を増やさないことを確かめる。

## PR

- 本文: `Closes #159`、`Closes #112`、`Closes #126`、`Closes #132`。
- 未対応の Minor と not run の項目を本文に書く。
- 区分は境界。PR 前に二重レビューを行い、両者の全文を PR コメントに載せる。

## リリース判定

想定は PATCH（候補 v14.1.2）。

- #159: 起動の止まり方が変わるのは、`.claude.json` が無いか型違いの構成だけ。#159 の再現ログのとおり、欠落した構成は今も Codex 経路では compose の段階で rc=126 で失敗しているので、動いていた構成が止まることは無いと見込んでいる。Claude 経路については、Task 1 の最初の実測で確かめる。動いていた構成が止まると分かったら、持ち主に判定を返す。
- #112-1: `AGENTS_DIR` の解決結果が変わるのは、symlink の後に `..` がある指定だけ。今はカーネルと違うディレクトリを黙って使っているので、不具合の修正として扱う。
- #112-2: 実体名にコロン・制御文字・末尾の改行がある構成だけが止まる。今は compose の短い書式を壊すか、別のディレクトリへ流れている。

区分: 境界 — `c3c` の起動ガード（入力検証と fail-closed）を足し、`AGENTS_DIR` の解決を変え、`:ro` 保護の検査（`CONFIG_RO_PROBE`）を変えるため（3 段階すべての二重レビュー）。
推奨実装: Opus — セキュリティ境界（起動ガードと `:ro` 保護の検査）を含むので、全体規則の「Opus はセキュリティ境界を含むときに推す」に当たる。さらに、#159 の今の挙動の実測、#126-3 の前提が崩れたときの判断、#132-4 の errno の実測など、実装中に判断が残る（判定基準の 3）。実 Podman を使うので、host で逐語手順だけを実行する Codex（判定基準の 4）には当たらない。Sonnet は、境界の追随漏れ（フィクスチャの範囲、不変条件の更新）の較正を要するので推さない。
実装: Opus（持ち主指定、2026-09-25。計画を書いたこのセッションが続けて実装する）

## 計画レビューの記録

2026-09-25 初回。Codex（`codex exec --sandbox read-only`）と Claude（`claude-opus-5-5`、headless、Read/Grep/Glob のみ）が独立にレビューした。両者とも「見直しが必要」。

- **両者が挙げたもの:**
  - `normalize_instruction_path` を通すと、`AGENTS_DIR=/` が ERROR になって #112-3 と矛盾する（Claude は Critical、Codex は Important。重い方を採った）。
    - 持ち主の判断で、#112-1 を `cd -P` にする方針に変えて解消した。
    - `..` の拒否は互換性を壊す（Codex の Important 5）ことも、変更の理由になった。
  - `.claude.json` のガードの配置と基点の解決の一致（Claude B-2、Codex の Important 2）→ 副作用の無い共通の解決関数と、`guard_ipv6` の直後への配置にした。
  - `--check .` の二重 FAIL の直し方が、ほかの対象の診断を止める（Claude B-6、Codex の Important 4）→ 対象ごとに外す方式にした。
  - 推奨実装は Opus であるべき（Claude B-8、Codex の Important 6）→ Opus にした。
- **Claude だけが挙げたもの:**
  - フィクスチャの範囲と、否定側のテストのすり抜け（B-3）→ 範囲を名指しし、完全版のテストを検証に足した。
  - lint の needle を `compose_mount_is_ro` に置き換える（B-7）→ 反映した。
  - README と不変条件の追随（B-9）→ Files に足した。
  - Minor（B-10〜B-15）→ 反映した。
- **Codex だけが挙げたもの:**
  - 成功ケースに失敗の Expected を課していた。compose を呼ばないことの判定方法（Important 3）→ 失敗と成功を分け、compose 専用の記録で見るようにした。
  - Minor 1・2 → 反映した。
- **反映しなかったもの:**
  - Claude B-4（Codex 専用の構成が止まる）: #159 の本文に、Codex 経路が今も rc=126 で失敗する再現ログがある。ただし Claude 経路は未実測なので、Task 1 の最初に実測を置いた。
  - Claude B-5 と A-2（隣のディレクトリは正しく解決されるはず）: 2026-09-25 の bash の実測で、`pwd -L` が相対の `../sibling` を返すことを確かめた。期待値は「止まる」のままにした。
- **確認限定巡（同日）:**
  - Claude（`--resume`）は、前回の指摘をすべて解消と判定した。修正で新しく生じた Important が 1 件あった。#112-2 の番兵を `$(pwd -P)` の外に付けると、末尾の改行が落ちる。これを `c3c:2427` と同じく置換の中で `$PWD` に付ける方式に直した。
  - Minor 2 件（Codex 経路への限定、目的の表現）も反映した。
  - Codex（新しい `codex exec`）は、前回の 1・3・5・6 を解消と判定した。同じ番兵の件に加えて、次の 2 点が未完了とした。
    - 2: plugin の別名用の未解決の綴りの保持、副作用の分離、symlink と `..` の一致テスト → Task 1 に明記した。
    - 4: `--clean-missing` の `targets` の置き換えで、外した `.` が消える → 保持して戻す手順と、混在ケースのテストを足した。
- 2 巡目の確認限定巡（同日）: Claude（`--resume`）は「実装に渡せる」と判定した。Minor 2 件（失敗の種類を返す、テストの期待を論理側に置く）を注記として足した。
- 2 巡目の確認限定巡（同日）: Codex（新しい `codex exec`）は、前回未完了とした項目をすべて解消と判定し、「実装に渡せる」とした。これで両レビュアーとも「実装に渡せる」になった。計画の静的なレビューで、実装・テストは not run。
