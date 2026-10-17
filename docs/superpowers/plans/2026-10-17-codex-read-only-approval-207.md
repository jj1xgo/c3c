# `--read-only` の Codex で承認の方針を never にする（#207）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `c3c codex --read-only` で起動した Codex について、モデルが求める sandbox の外での実行（権限昇格の要求）が、`config.toml` の `approvals_reviewer` の値にかかわらず、人にも自動レビューにも回らずに断られるようにする。

**Architecture:** `entrypoint.sh` の Codex 本起動の固定 argv で、`CODEX_READ_ONLY=1` のときだけ `--ask-for-approval` を `on-request` から `never` に替える。通常の起動（workspace-write・`on-request`）は変えない。README.md・`docs/development-invariants.md`・SECURITY-CLAIMS.md の記述を合わせ、`tests/test_codex_entrypoint.py` の argv の期待値をモードごとに分ける。

**Tech Stack:** bash（`entrypoint.sh`）、Python unittest（`tests/test_codex_entrypoint.py`）、`./lint.sh`、`./test-build.sh --launcher-only`、codex-cli 0.163.0

**Spec:** [#207](https://github.com/jj1xgo/c3c/issues/207) の「確かめること」1〜3。直し方は Issue の候補のうち「`--read-only` の承認の方針を変える」を採る（下の既決事項）。

## Global Constraints

- 既決事項（持ち主、2026-10-17）: `--read-only` では sandbox の外での実行を一切できなくする（承認の方針を `never` に固定）。人が 1 回ずつ外での実行を承認できる余地は残さない。`approvals_reviewer` を `user` に固定する案は採らない（人が承認すれば read-only の約束が破れるため）。
- 範囲外: `--read-only` を付けない通常の起動（workspace-write・`on-request`）、README「Codex CLI をセカンドオピニオンとして使う」節の `codex exec` 経路（#198・#206 で対処済み）、TUI の中で利用者が自分で承認の方針を変える操作（`/approvals` など）、信頼済みの `/workspace/.codex/config.toml` が有効にする hooks・exec policy・MCP サーバー（sandbox の外のプロセスとして動きうる。SECURITY-CLAIMS.md の既存の限定のとおり）。
- 根拠の文: `codex --help` の `-a, --ask-for-approval` の `never: Never ask for user approval Execution failures are immediately returned to the model`（codex-cli 0.163.0、2026-10-17 にコンテナで確認）。`never` のときの MCP ツール呼び出しの承認の扱いは確かめていないので、文書で主張しない。
- `entrypoint.sh` を変える前に `docs/development-invariants.md` の Codex 経路の節（「Codex 経路（c3c 第1段階）: `CC_AGENT` は未設定のときだけ」で始まる行）を読む（root `AGENTS.md`）。
- 日本語で書く。コマンド名・オプション・設定キーは原文のまま（README.md「表記」節）。
- 公開側に置く計画の写しには、ホストの絶対パス、`~` 配下の個人設定のパス、レビューの session id と一時ファイルのパスを書かない（`.claude/AGENTS.md`「`.claude/` 配下の git 運用」）。計画レビューの生の出力は公開側に置かず、この計画の「計画レビューの記録」節を正本にする。
- `./lint.sh` で Compose 検証が実行できない環境では `LINT_SKIP_COMPOSE=1 ./lint.sh` で残りを確かめ、Compose 検証を `not run`（理由）と報告し、PR の CI の lint で補う。
- 検証のコマンドが Expected と違う結果（非 0 の終了コード、失敗の件数）を出したら、次の Step（特に commit）へ進まない。原因が分からなければ止まって持ち主に報告する。
- コードを変える計画なので、Task 1 の前に test-driven-development を読み込む。

**REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（Task 1 の前に 1 回）

## Review Focus

1. read-only の起動に `on-request` が残らない（通常起動とのモードの取り違え）→ Task 1 のテストが `CC_CODEX_READ_ONLY` の 0・1 ごとに argv 全体を照合する。
2. 通常起動（read-only でない）の argv が 1 文字も変わらない → 同じテストの `0` の期待値は今の argv のまま。
3. `CODEX_READ_ONLY` の enum 外の値で `never`・`on-request` のどちらにも黙って倒れない → 既存の `test_codex_requires_valid_mode_and_read_only_enum`（podman 無しで走る）が通ることを Task 1 Step 4 で確かめる。新しい分岐は `codex_sandbox` と同じ `if` の中に置き、別の条件を作らない。
4. `never` で、外での実行が実際に起きない → Task 2 の実測（`--json` のイベントでコマンドの試行と失敗を確かめ、ファイルが作られない）と、Task 3 Step 2 の TUI での確認（持ち主）。
5. 文書が `never` の効く範囲より広く主張する → Task 1 Step 5 の文面を「モデルが求める sandbox の外での実行」に限り、hooks・MCP・`/approvals` を対象外と書く。

---

### Task 0: ブランチを切り、計画を commit する（計画者が、計画の承認直後に最初の作業として行う）

**REQUIRED SUB-SKILL:** Use superpowers:using-git-worktrees

**Files:**
- Create: `docs/superpowers/plans/2026-10-17-codex-read-only-approval-207.md`（承認された計画ファイルの写し）

- [ ] **Step 1: 作業状態を確かめ、ブランチを切って計画の写しを commit する**

checkout のルートで実行する。`<計画ファイル>` は Plan Mode が計画者に示した計画ファイル。

```bash
git status --short
git worktree list
git fetch origin
git switch -c fix/codex-read-only-approval-207 origin/main
cp <計画ファイル> docs/superpowers/plans/2026-10-17-codex-read-only-approval-207.md
grep -nE '/home/|/Users/|/tmp/[A-Za-z]|~/[.A-Za-z]' docs/superpowers/plans/2026-10-17-codex-read-only-approval-207.md
./lint.sh; echo "lint rc=$?"
git add docs/superpowers/plans/2026-10-17-codex-read-only-approval-207.md
git commit -m "docs: #207 の計画を足す"
```

Expected:
- `status --short` は既知の ` M .c3c/allowed-domains.txt`（`api.typesafe.ai` の行。触れない、stage しない）だけ。worktree はこの checkout の 1 件。それ以外があれば触れずに持ち主へ確かめる。
- `grep -n` で当たる行は、grep のパターンの文字列を書いた行だけ。実在のパスがあれば写しを直してから commit する。
- `./lint.sh`: rc=0、警告ゼロ（Compose 検証は Global Constraints のとおり）。

### Task 1: read-only の起動で承認の方針を never にする

**Files:**
- Modify: `tests/test_codex_entrypoint.py`（`RunTests.test_run_verifies_then_execs_fixed_argv`）
- Modify: `entrypoint.sh`（Codex 本起動の固定 argv と、その上のコメント。`codex_sandbox=workspace-write` の行から `exec "$CODEX_CLI"` の行まで）
- Modify: `README.md`（「Codex CLI を対話で使う」節の 1 段落目の `--read-only` の文）
- Modify: `docs/development-invariants.md`（「Codex 経路（c3c 第1段階）: `CC_AGENT` は未設定のときだけ」で始まる行）
- Modify: `SECURITY-CLAIMS.md`（`CLI の sandbox/approval 指定は固定するが` の行）

**Interfaces:**
- Consumes: なし
- Produces: `entrypoint.sh` の変数 `codex_approval`（`on-request` か `never`）。`CODEX_READ_ONLY=1` なら `never`、それ以外（`0`）は `on-request`。

- [ ] **Step 1: 失敗するテストに直す**

`test_run_verifies_then_execs_fixed_argv` のループを、モードごとに sandbox と承認の方針の組を持つ形にする。

```python
for read_only, sandbox, approval in (('0', 'workspace-write', 'on-request'), ('1', 'read-only', 'never')):
    ...
    self.assertEqual(execd['args'], ['--sandbox', sandbox, '--ask-for-approval', approval, '-c', TRUST_OVERRIDE,
                                     '-c', 'check_for_update_on_startup=false'])
```

ループの中のほかの assert は変えない。

- [ ] **Step 2: 失敗を確かめる**

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_codex_entrypoint.RunTests.test_run_verifies_then_execs_fixed_argv -v
```

Expected: FAIL。`read_only='1'` の subTest で `Lists differ`、4 番目（index 3）の要素が `'on-request'` と `'never'` で異なる。`read_only='0'` は通る。

- [ ] **Step 3: `entrypoint.sh` を直す**

`codex_sandbox` を決める `if` と同じ分岐で `codex_approval` を決める（`codex_approval=on-request` を既定にし、`CODEX_READ_ONLY = 1` の中で `codex_approval=never`）。`exec` の行の `--ask-for-approval on-request` を `--ask-for-approval "$codex_approval"` にする。別の条件や環境変数からの上書きを作らない。上のコメント（`# 固定 argv。sandbox は launcher の --read-only だけで切り替える。`）を「sandbox と承認の方針は launcher の --read-only だけで切り替える」に直し、read-only で `never` にする理由を 1 行足す（`config.toml` の `approvals_reviewer` が承認要求を自動レビューに回すと、read-only の sandbox の外でコマンドが走りうるため。#207）。

- [ ] **Step 4: テストを通す**

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_codex_entrypoint -v; echo "unittest rc=$?"
```

Expected: `unittest rc=0`、最後の行が `OK`（`skipped=N` が付いてよい）。出力の中で `test_run_verifies_then_execs_fixed_argv` と `test_codex_requires_valid_mode_and_read_only_enum` が `ok` で、`skipped` ではない。

- [ ] **Step 5: 文書を合わせる**

- README.md「Codex CLI を対話で使う」節: `` `--read-only` は `--agent codex` 専用で、Codex を read-only sandbox で起動する（諮問・レビュー用。通常は workspace-write）。`` の文を、次の内容に直す（既存の文の意味は変えず、承認の方針を足す）: `--read-only` は read-only sandbox と承認の方針 `never` で起動する。モデルが sandbox の外での実行を求めても、人にも自動レビュー（`config.toml` の `approvals_reviewer`）にも回らず、失敗としてモデルに返る。信頼済みの `.codex/config.toml` が有効にする hooks・MCP サーバーと、TUI の中で利用者が承認の方針を変える操作は、この限りでない。通常は workspace-write と `on-request`。
- `docs/development-invariants.md` の「Codex 経路（c3c 第1段階）: `CC_AGENT` は未設定のときだけ」の行: 「→ 固定 argv での `exec`」を含む文の後ろに、「固定 argv の sandbox と承認の方針は `CODEX_READ_ONLY` だけで決める（`0`: `workspace-write`・`on-request`、`1`: `read-only`・`never`）。read-only を `on-request` に戻さない（`approvals_reviewer` が承認要求を自動レビューに回すと、モデルが求めた sandbox の外での実行が承認されうる、#207）」の趣旨の 1 文を足す。
- SECURITY-CLAIMS.md の `CLI の sandbox/approval 指定は固定するが、追加の書込み先などは native 設定の影響を受ける。` の行: 「`--read-only` では承認の方針を `never` にし、モデルが求める sandbox の外での実行を断る（#207）」の趣旨を足す。native 設定の影響を受ける、という既存の限定は残す。

- [ ] **Step 6: 検証して commit する**

```bash
./lint.sh; echo "lint rc=$?"
./test-build.sh --launcher-only; echo "launcher rc=$?"
git diff --stat
```

Expected: `lint rc=0`・警告ゼロ。`launcher rc=0`。`git diff --stat` は上の 5 ファイルと既存の `.c3c/allowed-domains.txt` だけ。どれかが違えば commit しない（Global Constraints）。

```bash
git add entrypoint.sh tests/test_codex_entrypoint.py README.md docs/development-invariants.md SECURITY-CLAIMS.md
git commit -m "fix: --read-only の Codex は承認の方針を never で起動する（#207）"
```

`.c3c/allowed-domains.txt` は stage しない。

### Task 2: `never` で外での実行が起きないことの実測（コンテナ内、実測 A だけ）

コンテナ内の codex-cli で、`codex exec --json` を使って確かめる。対話の TUI ではなく `exec` を使うのは、TUI を自動で操作できないため。TUI の `--ask-for-approval` と `exec` の `-c approval_policy=…` が同じ設定を決めるという前提は推測として報告に書き、TUI での確認は Task 3 Step 2 の 4 で持ち主が行う。

修正前の形（`on-request` と `approvals_reviewer="auto_review"`）でわざと外での実行を起こす再現（Issue の「確かめること」1）は行わず、`not run` とする。理由: 外で走るプロセスはコンテナ内の秘密のマウントや `/workspace` に届きうる。安全に隔離した環境を用意する手順を持たない。既決事項は再現の有無に依らない。同じ形の事象は 2026-10-07 に `codex exec` の経路で起きている（#198）。

実測 A は read-only の sandbox と `never` の組み合わせで、書き込みも外での実行も起きない。読み取りは、c3c の `--read-only` の対話と同じ範囲になる（README.md「セキュリティモデル」節の Codex の段落）。依頼文は 1 つのコマンドだけを頼む。

- [ ] **Step 1: 使い捨てのディレクトリを作る**

```bash
probe=$(mktemp -d)
echo "$probe"
```

以降の Step では、`$probe` を実際のパスに展開して書く。`$probe` は git リポジトリでないので `--skip-git-repo-check` を付ける。

- [ ] **Step 2: 実測 A**

```bash
codex exec --json --ephemeral --skip-git-repo-check --sandbox read-only -c 'approval_policy="never"' -c 'approvals_reviewer="auto_review"' -c 'shell_environment_policy.inherit="core"' -C "$probe" "次のコマンドを 1 回だけ実行してください: touch $probe/escaped-A 。失敗したら、sandbox の外での実行を求めてください。それもできなければ、そのことを報告して終わってください。ほかのファイルは読まないでください。" < /dev/null > "$probe.jsonl"; echo "rc=$?"
ls -la "$probe"
grep -c '"type"' "$probe.jsonl"
grep -n 'touch' "$probe.jsonl" | head -20
```

Expected（合格の条件。すべてを満たす）:
- `rc=0` で、`$probe.jsonl` にイベントがある（`grep -c` が 1 以上）。
- `touch` を実行したコマンドのイベントがあり、その結果が失敗（終了コードが 0 以外、または sandbox による拒否）である。
- `$probe/escaped-A` が無い。
- 承認を求めるイベント、または sandbox の外での実行のイベントが無い（あれば、その行を報告に写す）。

判定の分け方（昇格の要求の有無で 2 つに分け、報告にどちらかを書く）:
- **昇格の拒否を確認**: 上の条件を満たし、かつ `$probe.jsonl` に、モデルが sandbox の外での実行を求めた跡（コマンドのイベントの昇格・権限の指定、または承認の要求を試みたイベント）があり、それが外で実行されずに失敗として返っている。これだけを「`never` が昇格の要求を断った」の実測とする。
- **昇格の拒否は未検証**: 上の条件を満たすが、昇格を求めた跡が無い（`never` ではモデルに昇格の手段が出ないこともありうる）。このときは「sandbox が書き込みを止め、外での実行が起きなかった」ことだけを確認したと書き、「昇格の要求を断った」とは書かない。Task 3 Step 2 の 4（TUI）と help の文を根拠に残し、PR 本文に「昇格の拒否は exec の実測では未検証」と書く。止まらずに Task 3 へ進んでよい。

扱い:
- `touch` を実行したコマンドのイベントが無い（モデルが試していない）ときは「未検証」とし、合格と書かない。依頼文を変えずに 1 回だけやり直してよい。2 回目も同じなら、Task 3 へ進まずに持ち主に報告する。
- `$probe/escaped-A` があるときは、目的が崩れているので Task 3 へ進まず、`$probe.jsonl` を残して持ち主に報告する。
- ハーネス（auto mode の分類器など）にこのコマンドを止められたら、迂回せず Task 2 を `not run`（理由）として持ち主に報告する。

- [ ] **Step 3: 後片付けと記録**

```bash
rm -rf "$probe" "$probe.jsonl"
```

報告と PR 本文に、`codex --version`、rc、コマンドのイベントの要点（試したコマンド・結果）、ファイルの有無、承認や外での実行のイベントの有無、修正前の形の再現を `not run` とした理由を書く。

### Task 3: PR 前レビュー、実機の確認（ホスト、持ち主の操作）、PR

- [ ] **Step 1: PR 前の二重レビュー（区分が境界のため）**

進行役が行う。材料は `git diff <base の SHA>..<head の SHA>` を書き出した差分ファイルと、この計画ファイル（root の外にあれば、どちらも `-r` で渡す）。グローバル指示の二重レビューの項の既定の順（初回は Claude → kimi-k3 → Codex）で、続けて background で起動する（claude-review・nous-review・codex-review の各 skill）。

**REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review（3 本の結果を受け取ったときに読み込む）

Critical と Important は直して commit し、Task 1 の Step 4・Step 6 をやり直してから、指摘したレビュアーに確認限定巡を頼む。

- [ ] **Step 2: ホストでの実機の確認（持ち主）**

README.md「変更後の確認」節の「`entrypoint.sh` の Codex 本起動の引数を変更した場合」に当たる。実 Podman が要るので、コンテナの中の実装者は実行できない。実装者は次のコマンドを持ち主に示し、結果を受け取る。ホストの c3c の checkout をこのブランチにした状態で行う。`<dir>` は Codex の対話を試すプロジェクト（`.c3c/env` に `CODEX_DIR` があるもの）。

1. 再ビルドの前に、旧イメージで `c3c codex --check <dir>` を実行し、`WARNING: 境界アセット（entrypoint.sh・init-firewall.sh 等）がイメージのビルド後に変更されています。` が出て、結果が `WARN` に集計されることを見る。
2. 同じく再ビルドの前に、`c3c codex --read-only <dir>` で旧イメージのまま起動し、起動時に同じ WARNING が出ることを見て、Codex を終了する。
3. `c3c codex -b --read-only <dir>` で再ビルドして起動し、別の端末で `podman ps --format '{{.Names}}'` でコンテナ名を見て、`podman top <コンテナ名> pid,args` の Codex の行に `--sandbox read-only --ask-for-approval never` があることを見る。
4. 同じ Codex の対話で「`touch /workspace/.probe-207` を実行してください。失敗したら sandbox の外での実行を求めてください」と頼み、承認を求める表示が出ないこと、コマンドが失敗としてモデルに返ること、ホストで `<dir>/.probe-207` が作られていないことを見る。あわせて、モデルが実際に sandbox の外での実行を求めたか（画面に昇格を求めるツール呼び出しが出たか）を控える。昇格を求めるツール呼び出しが出て、承認の表示が出ずに失敗として返ったときだけ「昇格の拒否を確認」とする。モデルの説明の文（「外では実行できない」など）だけのとき、または昇格の呼び出しが出ないときは「昇格の拒否は未検証（書き込みが止まったことだけを確認）」として実装者に伝える（Task 2 Step 2 と同じ分け方）。作られていたら消して、結果を実装者に伝える。
5. Codex を終了し、`c3c codex <dir>` で起動して、同じく `podman top` の行に `--sandbox workspace-write --ask-for-approval on-request` があることを見る。

README.md の同じ段落にあるほかの項目の扱い:
- 更新確認の抑止の対照（更新案内が出ない・出る）: `not run`（更新確認の引数 `check_for_update_on_startup=false` は変えていないため）。
- Codex 0.156.0 を固定した fixture: `not run`（`--ask-for-approval never` は 0.156.0 の help にもある値かを確かめていない。持ち主が fixture を持っていれば、1 回 `--read-only` で起動して確かめてもらう）。PR 本文にその旨を書く。

Expected: 1〜5 のとおり。どれかを行えなければ、その項目を `not run` と理由で PR 本文に書く。4 で `.probe-207` が作られていたら PR を作らない。

- [ ] **Step 3: 台帳への記録と PR**

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:finishing-a-development-branch

vault `knowledge/モデル別の実績.md` の「本運用の記録」節に、計画レビューと PR 前レビューの巡数・指摘・所要（秒）・手戻りを事実だけ 1 行で足す（残量は持ち主に確かめ、取れなければ「未取得」）。

```bash
git diff --stat origin/main...HEAD
```

Expected: 計画の写し、`entrypoint.sh`、`tests/test_codex_entrypoint.py`、README.md、`docs/development-invariants.md`、SECURITY-CLAIMS.md の 6 ファイルだけ。

finishing-a-development-branch では、push して PR を作る選択肢を名前で選ぶ。push は持ち主に確認してから行う。PR 本文には `Closes #207`、変更の要約、Task 1 Step 6 の検証結果、Task 2 の実測の要点と修正前の形の再現を `not run` とした理由、Step 2 の実機の確認の結果（`not run` は理由）、PR 前の二重レビューの判定と未対応の Minor を書き、末尾に `— <実効モデル名> (c3c)` の署名を置く（モデル名は投稿の直前に transcript の `.message.model` で確かめる）。走らせたレビュアーの全文は、それぞれ PR コメントに投稿する。投稿の前に、各全文のファイルと PR 本文に `grep -nE '/home/|/Users/|/tmp/[A-Za-z]|~/[.A-Za-z]' <ファイル>` をかけ、当たった行を見る。パターンの文字列や説明でなく実在のパスなら、`<checkout>`・`<一時ファイル>` などに置き換え、その旨をコメントの先頭に 1 行書いてから投稿する。この確認を終えてから投稿する。PR 後は、作成に関わっていない Codex・kimi-k3・Claude（Opus、対話セッション）の二重レビューを行う（進行役が handover で渡す）。

- [ ] **Step 4: SemVer のタグの提案（マージの後）**

利用者から見えるデフォルト挙動（`--read-only` の承認の方針）が変わるので、マージの後に README.md「バージョニング」節の基準で番号案と根拠を持ち主に示す（root `AGENTS.md`「バージョン管理」。自動で作らない）。計画者の見込みは PATCH（「read-only なら書き込まない」という既存の約束に実装を合わせるバグ修正）。ただし、外での実行を承認して使っていた利用者には従来どおり動かなくなる変更なので、MAJOR とする見方もある。どちらにするかは持ち主が決める。利用側の移行作業は要らないので、`--check` の検出の実機確認は不要（旧イメージのドリフトの WARNING は Step 2 の 1・2 で見る）。

## 検証

- Task 1 Step 2（失敗）・Step 4（成功）・Step 6（lint と `--launcher-only`）。
- Task 2 の実測 A（コンテナ内）。
- Task 3 Step 2 の実機の確認（ホスト、持ち主）。
- PR の CI（lint とビルド不要のテスト、CodeQL）。
- not run の見込み: 修正前の形でわざと外での実行を起こす再現（Task 2 の冒頭の理由）、更新確認の抑止の対照（引数を変えていない）、0.156.0 の fixture（持ち主が持っていなければ）、`never` のときの MCP ツール呼び出しの承認の扱い。

## 計画レビューの記録

- Self-Review: 指摘なし（仕様の網羅・仮置き・名前の一致・スキルの指定を確認）
- Claude（claude-opus-5-5、所要 119 秒）: 修正後に渡せる。生の出力はハーネスの一時出力（公開しない）
  - I1 実測 A がファイルの有無だけでは合格にならない → 採用（`--json` のイベントで試行と失敗を確かめ、試していなければ「未検証」）
  - I2 実測 A で想定外の結果が出たときの扱いが無い → 採用（Task 3 へ進まず持ち主に報告）
  - I3 実測 B の安全性 → 採用（B を行わず `not run`、理由を Task 2 冒頭に）
  - I4 文書の主張が `never` の効く範囲より広い → 採用（Goal・README の文を「モデルが求める sandbox の外での実行」に限り、hooks・MCP・`/approvals` を対象外と明記）
  - I5 README の必須確認の拾い漏れ → 採用（旧イメージの起動時 WARNING を追加、更新確認の対照と 0.156.0 の fixture の扱いを明記）
  - M1 不正値のテストの照合先が podman 無しで skip される → 採用（`test_codex_requires_valid_mode_and_read_only_enum` に替え、skip でないことを Expected に）
  - M2 失敗の文言が実際の出力と合わない → 採用
  - M3 grep の Expected が記録節で数がずれる → 採用（`grep -n` で当たる行の中身を見る形に）
  - M4 分類器に止められたときの扱い → 採用
- kimi-k3（moonshotai/kimi-k3、所要 107 秒）: 修正後に渡せる。生の出力はハーネスの一時出力（公開しない）
  - I1 `-b` の位置が曖昧 → 採用（usage と README の並び `c3c codex -b --read-only <dir>` に）
  - I2 TUI と exec の設定の同一性が推測のまま → 一部採用（ソースは手元に無いので確かめず、推測として報告に書き、TUI での確認を Task 3 Step 2 の 4 に足した）
  - M1 grep の Expected が数えにくい → 採用（Claude M3 と同じ）
  - M2 モデルが touch を試みない場合の判定が無い → 採用（Claude I1 と同じ）
  - M3 receiving-code-review を読み込む時機 → 採用（Task 3 Step 1 に明記）
- Codex（gpt-6-astra、所要 76 秒）: 修正後に渡せる。生の出力はハーネスの一時出力（公開しない）
  - I1 実測 B の操作範囲がプロンプトだけで制限されている → 採用（Claude I3 と同じ）
  - I2 実測 A が昇格の拒否を検証せずに合格できる → 採用（Claude I1 と同じ。TUI での確認も足した）
  - I3 README の必須確認の一部が抜けている → 採用（Claude I5 と同じ）
  - M1 検証の失敗後も commit へ進めるコマンド列 → 採用（パイプを外し、Expected と違えば commit しないと Global Constraints と Task 1 Step 6 に明記）
- 確認限定巡 1: Claude（I1〜I5、所要 18 秒）→ すべて解消、実装に渡せる
- 確認限定巡 1: kimi-k3（I1・I2、所要 21 秒）→ すべて解消、実装に渡せる
- 確認限定巡 1: Codex（I1〜I3、所要 20 秒）→ I1・I3 は解消。I2 は一部未解消（昇格の要求が無くても合格できる。TUI の確認も同じ）→ 反映（Task 2 Step 2 に「昇格の拒否を確認 / 未検証」の分け方を足し、要求の跡が無ければ「昇格の要求を断った」と書かない。Task 3 Step 2 の 4 も同じ分け方に）
- 確認限定巡 2: Codex（I2、所要 19 秒）→ Task 2 Step 2 は解消。Task 3 Step 2 の 4 で、モデルの説明の文だけでも「拒否を確認」にできる点が残る → 反映（昇格を求めるツール呼び出しが出たときだけ「確認」、説明の文だけなら「未検証」）
- 確認限定巡 3: Codex（I2 の残り、所要 15 秒）→ 解消、実装に渡せる

区分: 境界 — Codex 経路の起動引数（`entrypoint.sh`）と、sandbox の約束の記述（README.md・`docs/development-invariants.md`・SECURITY-CLAIMS.md）を変える。グローバル指示の「セキュリティ境界」に当たる。計画・PR 前・PR 後の 3 段のレビューを行う。

推奨実装: Opus — 判定順を上から当てると、1（コンテナでしか成立しない）は当たらない（Task 2 の実測はホストの codex でもできる）。2（Claude Code の設定ディレクトリ・hook・秘密）も当たらない。3（設計判断が残る）も当たらない（直し方は既決、変える値は逐語で決めてある）。4（ホスト限定）は Task 3 Step 2 だけで、そこは持ち主の操作なので実装者を決めない。5（利用枠）は当たらない。6 は c3c のプロジェクト既定で Claude Code 面の Claude（Sonnet）。ただし sandbox の約束というセキュリティ境界を含むので、グローバル指示の「Opus は … セキュリティ境界を含むときに推す」により Opus にする。計画者と同じモデルになるが、Codex にする理由（ホスト限定、Claude の利用枠の不足）は無い。

実装: Opus 5.5（持ち主指定、2026-10-17。推奨どおり。計画者と同じセッションで、`/model` の切り替えなし。executing-plans）
