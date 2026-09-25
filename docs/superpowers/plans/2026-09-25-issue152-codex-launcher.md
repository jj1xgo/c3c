# #152: Claude 経路から呼ぶ Codex にも同梱 bubblewrap を選ばせる実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

## 目的と状態

Claude 経路のコンテナ（`CC_AGENT=claude`）の中から `codex` を名前で呼んだとき（`codex exec --sandbox read-only` を含む）も、Codex がシステム版 `/usr/bin/bwrap` ではなく同梱版を選ぶようにする。要件は [#152](https://github.com/jj1xgo/c3c/issues/152)。基準は `fd2dc4a`（v14.1.0 以降の main）、対応 Codex は `0.156.0`。前提の設計は #145（計画 `2026-09-23-codex-bundled-bwrap.md`、README「Codex CLI を対話で使う」節の sandbox の bubblewrap）。

2026-09-25 に計画レビューの初回を終え、指摘を反映した（末尾「計画レビューの記録」）。持ち主が実装者を指定するまで製品ファイルは編集しない。

技術: Bash、Dockerfile、Python unittest、Podman。新しい実行時依存は追加しない。

## 事実（2026-09-25 に確かめたこと）

- `entrypoint.sh:161-167`: `CODEX_BWRAP_DIR` を PATH の先頭へ足すのは `CC_AGENT=codex` の分岐の中だけ。Claude 経路の PATH は変えないことが、不変条件（`docs/development-invariants.md` 76 行目）と README 487 行目に書いてあり、`tests/test_codex_entrypoint.py:477` がそれを検査している。
- Claude Code の Bash ツールは、継承した PATH をそのまま使う。コンテナ内セッションの transcript（`~/.claude/projects/-workspace*/*.jsonl`）に残る PATH は、`/home/node/.local/bin:/usr/local/sbin:/usr/local/bin:...` に plugin の bin を足したもの。そのため、entrypoint で PATH を足す方式は Bash ツールには効く。
- 一方、ログインシェルは PATH を作り直す。findsummits のイメージで `PATH=/X/wrap:...` として `bash -lc 'echo $PATH'` を実行すると、`/home/node/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/local/games:/usr/games` になり、先頭に足した要素は消えた。Debian の `/etc/profile` の 7 行目が PATH を固定で代入するため。`podman exec` や利用者の `bash -l` から呼ぶ `codex` には、entrypoint の PATH は効かない。
- イメージ内の `/usr/local/bin/codex` は、npm が作った `../lib/node_modules/@openai/codex/bin/codex.js` への symlink（root 所有）。`/usr/local/libexec` と `/usr/local/libexec/c3c` は root 所有の 755。
- `/usr/local/bin/codex` を固定パスとして使う箇所は次のとおり。`grep -rn /usr/local/bin/codex` で、`docs/superpowers` と `.git` を除いて数えた（初版は文書の 3 か所を数え漏らしていた。計画レビューで判明）。
  - `Dockerfile.claude:220`（codex-bwrap RUN。`fs.realpathSync` で vendor を解決する起点）
  - `entrypoint.sh:163`（`CODEX_CLI`）
  - `test-build.sh:2063-2064`（`-x` を検査）、`test-build.sh:2229`（opt-out のとき不在であること）
  - `tests/test_codex_bwrap.py:25`、`tests/test_codex_entrypoint.py:24`（置換の固定文字列）
  - `docs/development-invariants.md:64`（「Codex CLI の実体は `npm install -g @openai/codex` が置く `/usr/local/bin/codex`」）と `:75`（`CODEX_CLI` の確定）、`README.md:538`（「CLI 実体 `/usr/local/bin/codex`（npm global bin）」）。今回の変更で記述が偽になるので Task 3 で直す。
- `codex.js` は自分の位置を `import.meta.url` と `realpathSync` で解決する。実体のパスを直接 exec しても、vendor の解決は変わらない。`process.argv[1]` は `detectPackageManager()` が使い、その結果は更新方法の案内と、子へ渡す `CODEX_MANAGED_BY_*` 環境変数の選択に効く。固定の npm 配置では、直接 exec しても起点が同じ npm ツリー内なので判定は変わらない見込み（推測。Task 4 で `codex --version` と更新案内の表示が従来と同じことを確かめる）。この版の `codex.js` は PATH を書き換えない。

## 設計判断

採用: **`/usr/local/bin/codex` を、c3c の起動口スクリプトに置き換える。** npm の symlink は消し、起動口が実体 `codex.js` を固定の絶対パスで exec する。起動口がすることは次の 3 つ。

1. 同梱のリンク `/usr/local/libexec/c3c/codex-bwrap/bwrap` について `-f` と `-x` を検査する。どちらかを満たさなければ、`ERROR: Codex 同梱の bubblewrap がありません。-b で再ビルドしてください。` を出して終了コード 1 で止まる。文言は entrypoint と同じにする。上流は存在しない候補や実行できない候補を飛ばしてシステム版を黙って選ぶので、この検査がないと、リンクが欠けたときに #152 と同じ `/proc` エラーへ黙って戻る。
2. PATH の先頭の要素が `CODEX_BWRAP_DIR` でなければ、先頭に足して export する。先頭が既にそれなら何もしない。冪等の定義は「先頭が同梱ディレクトリになり、既に先頭なら PATH を一字も変えない」とする（2 番目以降にある場合の重複は許す。上流の探索は先頭の候補を使うため）。PATH が空または未設定のときは `CODEX_BWRAP_DIR` だけにし、末尾の空要素（カレントディレクトリの意味になる）を作らない。
3. `exec /usr/local/lib/node_modules/@openai/codex/bin/codex.js "$@"` を実行する。引数、終了コード、シグナルはそのまま渡る。

この案を選んだ理由:

- 名前で `codex` を呼ぶ経路すべてに効く。Claude の Bash ツール、ログインシェル、`podman exec`、Codex の中からの再帰呼び出しが含まれる。どれも `/usr/local/bin` を PATH に含むので、この効き方は `/etc/profile` による PATH の作り直しに左右されない。
- Claude 経路の PATH は変わらない。Claude 本体と、Codex 以外の子プロセス（glycin-loaders が名前で呼ぶ `bwrap` や、Claude Code 自身の sandbox 機能など）は、従来どおり `/usr/bin/bwrap` を使う。PATH が変わるのは、起動口が exec した Codex の子孫だけ。これで、Issue が求める「Claude 本体や他の子プロセスへの影響の評価」に答えられる。不変条件の「Claude 経路の PATH は変えない」も改訂せずに済む。
- 信頼の置き方の変化を受け入れる。PATH で同梱版を選ぶと、上流の Bundled launcher が行うビルド時 digest との照合と `/proc/self/fd` 経由の exec を通らない（README 492 行目）。起動口はシステム版の無いイメージにも一律に効くので、Claude 経路から呼ぶ Codex も、上流の Bundled 経路から「PATH による選択と c3c のビルド時検査（root 所有・書込不可・help 4 項目）」へ移る。#145 が Codex 経路で受け入れた判断（信頼は npm による配布物の導入と root 所有のイメージに置く。c3c 独自の hash pin は足さない）を、名前で呼ぶ `codex` 全体へ同じように当てはめる。イメージごとに経路が分かれないことも、#145 の「常に同梱版を優先する」と同じ理由で採る。
- Codex 経路は、`CODEX_CLI=/usr/local/bin/codex` を通って起動口に入る。entrypoint が既に先頭へ足しているので、起動口は PATH を変えない。その結果、snapshot・verify・本起動の PATH の一致（#145 の不変条件）はそのまま保たれる。entrypoint の Codex 経路の検査と PATH の追加は外さない。起動口の検査と重複するが、審査より前に止める役割があるため。

採らなかった案:

- **Claude 経路でも `CODEX_BWRAP_DIR` を PATH の先頭に足す案。** Claude 本体とすべての子プロセスで、名前で呼ぶ `bwrap` が同梱版に変わる。Claude Code の sandbox 機能や glycin-loaders にも影響が及ぶ。ログインシェルと `podman exec` には効かない。不変条件の改訂も要る。
- **起動口を置く専用ディレクトリを、Claude 経路の PATH の先頭に足す案。** 影響は `codex` という名前に限られるが、Claude の PATH を変える点、ログインシェルと `podman exec` に効かない点は、上の案と同じ。
- **イメージ全体の `ENV PATH` に `CODEX_BWRAP_DIR` を足す案。** 効き方は上の 2 案と同じで、ログインシェルでは消える。影響はさらに広い。
- **sandbox の無効化、`unmask=/proc/*` の既定追加、システム版の撤去、エラー出力の書き換え。** #145 と Issue の指定どおり採らない。

起動口の置き方は、次の 2 案をレビューで比べてもらう。

- **(A) 推奨: リポジトリの独立ファイル `codex-launcher.sh` にする。**
  - 利点: `lint.sh` の shellcheck と unittest が、配布するスクリプトそのものに直接届く。ドリフト検知は (A)(B) で差がない（`guard_asset_drift()` は結合した単一のハッシュを比べ、どのアセットかは名指ししない。(B) でも `Dockerfile.claude` が `ASSET_HASH_TARGETS` に入っている）。計画レビューでは両レビュアーとも (A) を支持した。
  - 代償: 境界アセットの列挙へ追随が要る。`c3c` の `resolve_asset_source()`、`ASSET_HASH_TARGETS`、`stage_build_context()`、`test-build.sh` の `run_config_ro_launcher_tests()` と `stage_common_context()` の各コピー一覧、`Dockerfile.claude` の COPY。不変条件 22 行目の較正手順に従い、`entrypoint.sh` と `git-askpass.sh` の全参照を `grep -rn` で数え直してから追随する（`git-askpass.sh` は現時点で 9 ファイルから参照されている）。
- **(B) `Dockerfile.claude` の RUN の中で `printf` を使って生成する。**
  - 利点: 変更は Dockerfile に閉じる。
  - 代償: shellcheck が届かない。テストは、区切りで囲んだ RUN を抽出して実行する方式を新たに作る必要がある。既存の `# >>> c3c codex-bwrap` の区切りには混ぜない（あちらの抽出は `$` と `\` を含めない前提で成り立っている）。

## 共通の制約

- 次の不変条件を守る: `docs/development-invariants.md` の Dockerfile の節（65 行目の codex-bwrap の固定リンク）、entrypoint の節（76 行目の Codex 経路の PATH）、境界アセットの節（22 行目）。
- codex-bwrap RUN の vendor の解決は、npm の symlink を起点にしている。そのため、起動口に置き換える RUN はその後に置く。置き換える前に、symlink の realpath が起動口の固定パス `/usr/local/lib/node_modules/@openai/codex/bin/codex.js` と一致することを検査する。一致しなければビルドを止める（npm の配置が変わったとき、起動口が別物を exec しないようにするため）。
- 起動口の COPY 先は `/tmp/codex-launcher.sh` などの一時パスにし、`/usr/local/bin/codex` へ直接 COPY しない（直接置くと opt-out でも残る）。一時ファイルは同じ RUN で消す。
- opt-out（`codex-version.txt` が空）のときは起動口を置かない。`/usr/local/bin/codex` が存在しないことは、既存の `test-build.sh:2229` の検査が確かめる。判定には、Codex の install RUN と同じ正規化（`tr -d '[:space:]'`）と `set -e` を使う。
- 起動口は root 所有の 0755 にする。置き場の `/usr/local/bin` は、既存の `chown root:root /usr/local/bin ...` の後で root に固定されている。
- 起動口は秘密を読まず、環境変数による上書き口も作らない。固定パスは `readonly` にする。
- `CODEX_BWRAP_DIR` と fail-closed の文言が、起動口と `entrypoint.sh` の 2 か所に現れる。どちらの一致も、テストで `entrypoint.sh` の文字列と直接照合する。

## Task 1: 起動口のスクリプトとテスト

対象: `codex-launcher.sh`（新規。shebang は `#!/bin/bash`）、`tests/test_codex_launcher.py`（新規）、`test-build.sh` の `run_launcher_tests()`（706〜716 行目。unittest はファイル名で 1 本ずつ列挙されていて、CI は `--launcher-only` を実行するので、ここに `check "..." ... -p "test_codex_launcher.py"` を足さないと CI で走らない）。

- [ ] 起動口を書く。構成は上の設計判断の 1〜3 のとおり。
- [ ] テストは、固定パスを一時ディレクトリへ置き換えたコピーに対して行う（`tests/test_codex_entrypoint.py` と同じ方式）。確かめる挙動:
  - リンクがない、dangling、実行できないときは、終了コード 1 と規定の文言で止まり、実体を exec しない。
  - PATH の先頭に 1 回だけ足す。既に先頭にあれば PATH を変えない。
  - 引数（空白や `--` を含むもの）と、実体の終了コードをそのまま渡す。
  - 固定値と fail-closed の文言が、`entrypoint.sh` のものと一致する。
  - PATH が空・未設定のとき、末尾の空要素を作らない。起動の成否は問わない（空 PATH では `codex.js` の shebang `#!/usr/bin/env node` が `node` を見つけられず失敗する。置換前も同じなので後退ではない）。
  - わざと壊したら赤になることを、1 件以上手で確かめる（検査の行を外すなど）。
- [ ] 単独実行 `python3 -m unittest discover -s tests -p test_codex_launcher.py` が通り、`./test-build.sh --launcher-only` の一覧に新しい check が出て合格する。
- [ ] `./lint.sh` が終了コード 0、警告ゼロで通る。

## Task 2: イメージへの組み込みとアセット登録

対象: `Dockerfile.claude`（codex-bwrap RUN の後に、区切り付きの新しい RUN を置く）、`c3c`（`resolve_asset_source()`・`ASSET_HASH_TARGETS`・`stage_build_context()`）、`test-build.sh`（`run_config_ro_launcher_tests()` と `stage_common_context()` のコピー一覧、`--build-only` の検査）、`tests/test_network_timeouts.py:134-136`（staging 用の固定ファイルのコピー一覧）、`tests/test_c3c_config.py:442`（固定アセットの上書き拒否テスト）、root `AGENTS.md:16`（変更前に不変条件を読むファイルの一覧）。`tests/test_codex_launch.py:140` は `REPO.iterdir()` で全ファイルを写すので追随は要らない。

- [ ] 起動口を一時パスへ COPY し、opt-out でなければ、realpath の一致を検査してから `install -o root -g root -m 0755` で `/usr/local/bin/codex` に置き換える。opt-out のときは何も置かない。どちらでも一時ファイルは消す。
- [ ] 案 A のときは、アセット列挙のすべてに追随する。較正に使った grep の件数と、そのうち対象外とした参照を記録する。
- [ ] `test-build.sh --build-only` に次の検査を足す。
  - `/usr/local/bin/codex` が symlink でない通常ファイルで、root 所有の 0755、group と other から書き込めない。
  - 置換後も `codex.js` が起動口とは別の内容のまま残っている（`install` が symlink を辿って実体を上書きしていない）。
  - 最終イメージで `bash -lc 'codex --version'` が成功する。
  - opt-out のイメージには起動口がない。既存の `test-build.sh:2229` の検査で足りるが、`--build-only` は 2097〜2099 行目で終わり opt-out のビルドまで進まない。
- [ ] `--launcher-only` と `--build-only` に加え、引数なしの `./test-build.sh`（opt-out の実ビルドを含む全体実行）を実行する。実行できなければ理由とともに `not run` と書く。

## Task 3: 文書

- [ ] README の「Codex CLI を対話で使う」節（487〜494 行目）を直す。
  - 同梱版を選ばせる仕組みに、起動口を加える。
  - 「`podman exec` には自動では適用されない」という記述を、`/usr/local/bin/codex` に解決される呼び出しには経路を問わず効く、という内容に改める。node が書ける `/home/node/.local/bin` など、PATH でそれより前にある別の `codex` が選ばれた場合は対象外と書く。
  - 「子プロセスへの影響」（490 行目）と「信頼の置き方」（492 行目）の対象を、Codex 経路だけから「起動口を通る Codex すべて」へ広げる。
  - Claude 経路の PATH と、Claude の他の子プロセスが呼ぶ `bwrap` は変わらないことを明記する。
  - `/usr/local/lib/node_modules/@openai/codex/bin/codex.js` を直接呼んだときは起動口を通らないことを、対象外として書く。
- [ ] README「変更後の確認」節（730 行目）に、起動口の変更時に実行するテストを加える。
- [ ] `docs/development-invariants.md` 64 行目・75 行目と README 538 行目を、「`/usr/local/bin/codex` は c3c の起動口で、実体は `/usr/local/lib/node_modules/@openai/codex/bin/codex.js`」という内容に揃える。
- [ ] `docs/development-invariants.md` に、起動口の不変条件を足す。内容: 固定パス、fail-closed の文言と終了コード、冪等な PATH の追加、置換の順序と realpath の検査、opt-out では置かない、root 所有。76 行目の「Claude 経路の PATH は変えない」はそのまま残す。
- [ ] `entrypoint.sh` のコメント（152〜160 行目）に、`CODEX_CLI` が起動口を指すことを 1 行足す。挙動は変えない。
- [ ] `docs/codex-proc-investigation.md` に、#152 の受入の記録を追記する。

## Task 4: 実機での受入

システム版 `/usr/bin/bwrap` が残るイメージで確かめる。#145 の fixture（`.c3c/packages.txt` に `glycin-loaders` と `libgdk-pixbuf2.0-bin`）を `-b` で再ビルドする。

- [ ] Issue の完了条件: Claude 経路で起動した実際の Claude セッションの Bash ツールから、PATH に手を加えずに `codex exec --sandbox read-only` がシェルコマンド（`/bin/pwd`）を実行できる。
  - 認証済みのセッションが必要なので、持ち主の協力で行う。
  - `podman exec` のシェルと `bash -lc` から呼んだ場合も併せて確かめるが、これは補助の確認とする。
- [ ] `codex --version` と、起動時の更新案内の表示（出る場合）が、置換前のイメージと同じ（`detectPackageManager()` の判定が変わっていない）。
- [ ] Claude の Bash ツールから見た `command -v bwrap` が `/usr/bin/bwrap` のままで、Claude 本体の PATH が変わっていない。
- [ ] リンクを壊したコンテナでは、起動口が規定の文言で止まる。起動を中止したコンテナの書き込み層で行い、イメージは変えない。
- [ ] Codex 経路の回帰: `c3c codex -b` で、#145 の受入（read-only の `pwd` と workspace-write の `git status`、通信と mount の保護）をやり直す。
- [ ] `--check`: 修正前のイメージについて、境界アセットのドリフトが報告されることを実機で確かめる（PATCH を提案する前の要件）。
- [ ] 実行できなかった項目は、理由とともに `not run` と書く。

## リリース判定

想定は PATCH（候補 v14.1.1）。Claude 経路で Codex の sandbox が失敗する不具合の修正で、利用側の作業は再ビルドだけ。`/usr/local/bin/codex` が symlink から通常ファイルに変わるので、利用側がこのパスの symlink であることに依存している証拠が見つかれば、持ち主に判定を返す。タグは実装とレビューが終わってから提案する。

## 計画レビューの記録

2026-09-25 初回。Codex（GPT-6 Astra、`codex exec --sandbox read-only`）と Claude（`claude-opus-5-5`、headless、Read/Grep/Glob のみ）が独立にレビューした。どちらも Critical なし、判定は「修正後に渡せる」。

- 両者が挙げた Important: 新しい unittest が `run_launcher_tests()` に登録されず CI で走らない。`--build-only` では opt-out の実ビルドまで進まない。アセットの fixture（`tests/test_network_timeouts.py`、`tests/test_c3c_config.py:442`）の追随が明記されていない（Codex は Important、Claude は Minor。重い方を採った）。
- Claude だけが挙げた Important: 不変条件 64・75 行目と README 538 行目の記述が偽になる。「`--check` が名前付きで報告する」は誤り（Codex は Minor。重い方を採った）。Claude 経路の Codex も上流の Bundled 経路を通らなくなる、信頼の置き方の変化の評価が抜けている。
- Minor: `process.argv[1]` の影響の書き方（Codex）、冪等の定義と空 PATH、`install` の置換の確認、README の効く範囲の限定、文言の照合（Claude）。
- すべて本書に反映した。
- 確認限定巡（同日）: Codex（GPT-6 Astra、新しい `codex exec`）と Claude（`claude-opus-5-5`、初回の会話を `--resume`）の両方が、前回の指摘はすべて解消、判定「実装に渡せる」。Claude が補足した空 PATH のときの期待結果（起動の成否は問わない）を Task 1 に足した。
- これは計画の静的レビューで、製品の実装・ビルド・受入は not run。

区分: 境界 — `Dockerfile.claude` と境界アセットの列挙に触れ、Codex の sandbox が選ぶ bubblewrap と fail-closed の経路を変えるため（3 段階すべての二重レビュー）。
推奨実装: Opus — 境界の変更で、実コンテナで認証済みの Claude セッションと Codex 経路の受入まで行う必要があるため。Codex はコンテナ内の実測と Podman の再ビルドを一続きでこなしにくく、Sonnet は境界の追随漏れ（アセット列挙）の較正を要するため推さない。
実装: Opus（持ち主指定、2026-09-25。計画を書いたこのセッションが続けて実装する。実行方法は executing-plans）
