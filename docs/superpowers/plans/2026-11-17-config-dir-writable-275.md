# `~/.config` を node が書けるようにする（#275）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 対話のコンテナで node が `~/.config` の下に新しいディレクトリを作れるようにし、秘密のマウントの親 `~/.config/c3c` は node から改名も削除もできないままにする。

**Architecture:** `Dockerfile.claude` の root の層で、`/home/node/.config` を `root:root 1777`（sticky）、`/home/node/.config/c3c` を `root:root 755` で作る。`secrets` はイメージに作らず、今までどおりランタイムがマウント先として作る。sticky により、node は自分で作ったものしか改名・削除できない。

**Tech Stack:** Dockerfile（Podman build）、bash（`test-build.sh`）、Markdown（README・不変条件・設計）。

**Spec:** `docs/superpowers/specs/2026-11-17-config-dir-writable-design.md`（2026-11-17 持ち主承認。今は作業ツリーに未追跡で置いてある。Task 0 でブランチに commit する）

## Context

c3c#273（PR #274）の後に、findsummits が `c3c claude -b` で作り直したイメージで、Chrome・Brave・Firefox が起動直後に落ちる（#275）。原因は `/home/node/.config` が root 所有（ランタイムが作る `root:root 1755`）で、node が書けないこと。イメージにこのディレクトリが無いので、`compose.yml` の `${SECRETS_DIR:-/dev/null}:/home/node/.config/c3c/secrets:ro` のマウントの親として、ランタイムが作っている。findsummits は `XDG_CONFIG_HOME` を一時ディレクトリにする回避策で進めているが、修正を待っている。

`~/.config` を単純に node 所有にすると、node が `~/.config/c3c` を改名でき、Copilot の sandbox が `copilot-settings.json` の `deniedPaths`（`/home/node/.config/c3c/secrets`）で、パスだけで隠している秘密が別のパスに見える。そのため sticky の形を採る。

2026-11-17 の実測（findsummits のイメージ、`podman run --rm`）:
- `root:root 1777` の下で、node の `mkdir google-chrome` は成功した。root 所有の `c3c` の `mv` は `Operation not permitted`、`rm -rf` は `Permission denied` だった（bind マウント無し）。
- `~/.config` そのもの: `/home/node` は `node:node 700` なので、今のイメージでも node は `mv ~/.config ~/moved`（同じ親の中の改名）ができた。1777 にすると、別の親の下への移動（`mv ~/.config ~/sub/x`）もできるようになった。持ち主の判断（2026-11-17）: 今回は塞がず、既知の限界として不変条件・README・設計に書く。改名できるのは sandbox の外の node（秘密を既に読める主体）だけで、sandbox の中の Copilot からは `/home/node` が見えないため。

**TDD:** この計画はコード（`Dockerfile.claude`・`test-build.sh`）を変えるので、Task 1 の前に **REQUIRED SUB-SKILL:** Use superpowers:test-driven-development を読み込む。

## Global Constraints

- 秘密のマウントは `/home/node/.config/c3c/secrets` だけで、`:ro` 必須（`docs/development-invariants.md` の秘密のマウントの項）。マウント先と `compose.yml` は変えない。
- `secrets` のディレクトリはイメージに作らない（`SECRETS_DIR` が未設定のときは `/dev/null` が重なり、キャラクタデバイスになる。`entrypoint.sh` の `[ -d ]` の判別の前提）。
- `io.c3c.image-layout` は上げない。古いイメージは安全側に壊れるだけで、`Dockerfile.claude` は `c3c` の `ASSET_HASH_TARGETS` に入っているので、ドリフトの WARNING が `-b` を促す（Task 2 で実機で確かめる）。
- 「改名も削除もできない」と書くのは `~/.config/c3c`（とその中の `secrets`）についてだけにする。`~/.config` そのものの改名は防がない（既知の限界）と明記する。
- 編集のたびに `./lint.sh` を rc 0・警告ゼロで通す（root `AGENTS.md`）。
- 挙動の変更と README の変更は同じ commit にする（root `AGENTS.md`「挙動を変えたら README.md の該当節も同じコミットで更新」）。
- 作業はブランチ `fix/config-dir-writable-275` で行い、`main` に直接 commit しない。

## Review Focus

1. **`SECRETS_DIR` が未設定（`/dev/null` のマウント）**: `c3c/` を先に作っても、ランタイムが `c3c/secrets` に `/dev/null` を重ねられ、起動が失敗しないこと → Task 1 の `unset` の組（`[ -c ]` で判定。`env -u SECRETS_DIR` で呼び出し元の環境から外す）。
2. **`SECRETS_DIR` を設定した実構成（bind マウントがある）**: マウントがあっても sticky の効き目が変わらず、node が `c3c` と `c3c/secrets` を動かせないこと → Task 1 の `set` の組（ダミーの秘密だけを渡す）。
3. **runtime userns の構成**: uid の対応が違っても所有者・モードが同じに見えること → Task 1 Step 5 で `bash tests/test-runtime.sh` も走らせる（`env -i` のきれいな環境と `TEST_RUNTIME_USERNS=1` で `--build-only`・`--config-ro-only` を回し、本物の entrypoint の起動まで確かめる）。
4. **誰かが RUN を消す・`USER node` の後ろへ動かす**: CI で気づけること → Task 1 の層 2（`run_validator_layer2`）の静的検査。
5. **既存のイメージ**: `-b` するまで直らない。`--check` がドリフトを出すことを Task 2 で確かめ、README に書く。

---

### Task 0: ブランチを作り、設計を commit する

**REQUIRED SUB-SKILL:** Use superpowers:using-git-worktrees

**Files:**
- Modify: `docs/superpowers/specs/2026-11-17-config-dir-writable-design.md`（未追跡。main の作業ツリーにある）

- [ ] **Step 1: 状態を確かめる**

Run: `git status -sb && git worktree list && git log --oneline -2`
Expected: ブランチ `fix/config-dir-writable-275`（計画者が計画の commit のために `3e039c5` から作った）、HEAD は計画の commit、変更は未追跡の `docs/superpowers/specs/2026-11-17-config-dir-writable-design.md` だけ（違えば、ほかのセッションの変更を壊さないよう止まって持ち主に報告する）。

- [ ] **Step 2: ブランチを確かめる**

ブランチは計画者が作ってある。そのまま使う（worktree を使うなら、そのブランチから作り、未追跡の設計をその worktree に写す）。

- [ ] **Step 3: 設計の反目標と決めたことを、持ち主の判断に合わせて直す**

- 「反目標」の項: 守るのは `~/.config/c3c` の改名・削除・差し替えだと狭める。`~/.config` そのものは、今のイメージでも node が同じ親の中で改名でき、変更の後は別の親の下へも移せる（2026-11-17 実測）。これは既知の限界として塞がない（2026-11-17 持ち主の判断。改名できるのは秘密を既に読める sandbox の外の node だけ）、と書き足す。
- 「実装者に任せること」の 2 項は、この計画で決めた内容（検査は `test-build.sh` の `--build-only`・`--config-ro-only` と層 2、canary は変えない）に書き換える。

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-11-17-config-dir-writable-design.md
git commit -m "docs: ~/.config を node が書けるようにする設計（#275）"
```

### Task 1: イメージで `~/.config` を sticky、`~/.config/c3c` を root 所有で作り、文書を直す

**Files:**
- Modify: `test-build.sh`（`run_config_ro_tests()` の直前に `CONFIG_DIR_PROBE` を定義、`run_config_ro_tests()` に 2 つの検査、`--build-only` の Claude Code ツールの節〈`CLAUDE_MANAGED_SETTINGS_PROBE` の検査の後〉に 1 つの検査、`run_validator_layer2()` に静的検査）
- Modify: `Dockerfile.claude`（upgrade の RUN〈`apt-get clean; rm -rf /var/lib/apt/lists/*` で終わる RUN〉の直後、ビルド時アサーションの RUN〈コメント「このベースイメージがコンテナのセキュリティ境界が依存するものを提供しない場合」で始まる〉の前）
- Modify: `docs/development-invariants.md`（秘密のマウントの項〈「秘密のマウント（`SECRETS_DIR`）は `/home/node/.config/c3c/secrets` だけに載せ」で始まる行〉）
- Modify: `README.md`（「## GitHub トークンの配線」の中の `SECRETS_DIR` の手順〈「ホストの `SECRETS_DIR` はコンテナ内では `/home/node/.config/c3c/secrets` にマウントされる」の段落の近く〉、「## 変更後の確認」、Copilot の受け入れの段落〈「`/home/node/.config` には node が新しいディレクトリを作れないので」を含む段落〉）

**Interfaces:**
- Produces: シェル変数 `CONFIG_DIR_PROBE`（`test-build.sh` で `run_config_ro_tests()` の定義の直前に置く。`--config-ro-only` は早い段階で分岐して終わるので、それより後ろで定義すると空のまま `bash -c ""` が PASS する。コンテナの中の `sh -c` か `bash -c` で評価する検証式で、第 1 引数に `image`・`set`・`unset` のどれかを取る）

- [ ] **Step 1: 検証式 `CONFIG_DIR_PROBE` を書く**

node として評価し、次をすべて確かめる（どれか欠ければ理由を出して exit 1）:
- `[ "$(id -u)" != 0 ]`
- `/home/node/.config` は symlink でないディレクトリで、`stat -c %u:%g:%a` が `0:0:1777`
- `/home/node/.config/c3c` は symlink でないディレクトリで、`stat -c %u:%g:%a` が `0:0:755`
- `mkdir /home/node/.config/probe-275` が成功し、その `stat -c %u` が `id -u` と一致する（確かめた後に `rmdir`）
- `mv /home/node/.config/c3c /home/node/.config/c3c-moved` が失敗し、`/home/node/.config/c3c` がまだあり、`/home/node/.config/c3c-moved` が無い
- `rm -rf /home/node/.config/c3c` が失敗し、`/home/node/.config/c3c` がまだある
- `set`: `/home/node/.config/c3c/secrets` がディレクトリで、`cat /home/node/.config/c3c/secrets/seed` が `seed`。`mv /home/node/.config/c3c/secrets /home/node/.config/secrets-moved` が失敗する
- `unset`: `[ -c /home/node/.config/c3c/secrets ]`（`/dev/null` が重なっている）
- `image`: `/home/node/.config/c3c/secrets` が無い（`! [ -e ]`）。`probe-275` が残っていない（`ls -A` が `c3c` だけ、の形では判定しない。後の層の Claude Code のインストーラーなどが `~/.config` に何かを作っても崩れないように）
- 検証式は POSIX sh の範囲で書く（`--build-only` では `sh -c`、`--config-ro-only` では `bash -c` で評価するため）

- [ ] **Step 2: 検査を 4 つ足す**

- `--build-only` の節: `check "~/.config が root:root 1777 で、node が作れて c3c は動かせない（マウント無し）" podman run --rm --network=none "$IMAGE" sh -c "$CONFIG_DIR_PROBE" _ image`
- `run_config_ro_tests()` に、既存の 13 項目の検査と同じ `env ... podman compose "${compose_args[@]}" -p "$proj" --in-pod false run --rm -T --entrypoint bash claude-auth-workspace -c "$CONFIG_DIR_PROBE" _ <mode>` の形で 2 つ:
  - `set`: `mktemp -d` の下に `secrets/seed`（中身 `seed`）を作り、ディレクトリを `755`、`seed` を `644` にして、`SECRETS_DIR=<その secrets>` を渡す（ダミーの秘密だけを渡す）。
  - `unset`: `env -u SECRETS_DIR CLAUDE_CONFIG_DIR=... podman compose ...`（呼び出し元の環境の `SECRETS_DIR` を確実に外す）。
  - 一時ディレクトリは関数の既存の後片付けで消す。

Step 2 の後に `./lint.sh` を走らせ、rc 0・警告ゼロを確かめる。
- `run_validator_layer2()`: `Dockerfile.claude` に `install -d -o root -g root -m 1777 /home/node/.config` と `install -d -o root -g root -m 755 /home/node/.config/c3c` の行があり、どちらも最初の `USER node` の行より前にあることを確かめる。既存の層 2 の検査と同じ `[FAIL]` の出し方と `FAIL` の数え方にする。

- [ ] **Step 3: 失敗を確かめる**

**REQUIRED SUB-SKILL:** Use superpowers:systematic-debugging（下の Expected と違う理由で失敗したら〈ビルドの失敗、`podman tag` の失敗、既存の検査の FAIL など〉、止まらずにその場で原因を調べる。設計や Global Constraints を変えないと直らないと分かったら、そこで止まって持ち主に報告する）


Run: `./test-build.sh --validator-only`
Expected: 足した層 2 の検査が FAIL（行が無い）。
Run: `./test-build.sh --build-only`（ホストの Podman）
Expected: 足した `--build-only` の検査が FAIL（`/home/node/.config` が無い、または `0:0:1777` でない）。
Run: `./test-build.sh --config-ro-only`（`--build-only` が作ったイメージを使うので、その後に走らせる）
Expected: 足した 2 つが FAIL（ランタイムが作る `0:0:1755` で、`1777` でない）。PASS になったら検証式が空で評価されている（定義の位置の誤り）ので、Step 1 の置き場を直す。

- [ ] **Step 4: `Dockerfile.claude` に RUN を足す**

upgrade の RUN の直後（アサーションの RUN が root の層の最後のまま残る位置）に、理由のコメントを付けて足す。コメントには次を書く: sticky により node は自分のものしか改名・削除できず、Copilot の sandbox がパスで隠す秘密の親 `c3c` を動かせない。`secrets` を作らないのは、`SECRETS_DIR` 未設定時に `/dev/null` を重ねるため。`~/.config` そのものの改名は防がない（既知の限界）。#275。

```dockerfile
RUN set -e; \
    ! [ -L /home/node/.config ] || { echo "ERROR: /home/node/.config が symlink です" >&2; exit 1; }; \
    install -d -o root -g root -m 1777 /home/node/.config; \
    ! [ -e /home/node/.config/c3c ] || { echo "ERROR: /home/node/.config/c3c が既にあります" >&2; exit 1; }; \
    install -d -o root -g root -m 755 /home/node/.config/c3c
```

- [ ] **Step 5: 通ることを確かめる**

**REQUIRED SUB-SKILL:** Use superpowers:systematic-debugging（Step 3 と同じ扱い）

次を順に走らせる。
Run: `./test-build.sh --validator-only` → Expected: すべて PASS。
Run: `./test-build.sh --build-only` → Expected: 足した検査が PASS、既存の検査はすべて PASS のまま。
Run: `./test-build.sh --config-ro-only` → Expected: 足した 2 つが PASS、既存はすべて PASS。
Run: `bash tests/test-runtime.sh` → Expected: 最後の要約で `build`・`mounts`・`control-before`・`protected`・`control-after` がすべて成功（`not run` が出たら理由を控える）。

- [ ] **Step 6: 不変条件を直す**

秘密のマウントの項の末尾に、次の趣旨を足す。
- 親の `/home/node/.config` は `Dockerfile.claude` が `root:root 1777`（sticky）で、`/home/node/.config/c3c` は `root:root 755` で作る（#275）。
- node 所有にしない。node が `c3c` を改名でき、Copilot の sandbox がパスで隠す秘密が別のパスに見えるため。
- sticky を外さない。`secrets` をイメージに作らない（`SECRETS_DIR` 未設定時に `/dev/null` を重ねるため）。
- `~/.config` そのものは、node が改名・移動できる（既知の限界。改名できるのは秘密を既に読める sandbox の外の node だけ）。
- 形は `test-build.sh` の層 2・`--build-only`・`--config-ro-only` が確かめる。
- あわせて `Dockerfile.claude` の節にも 1 項目足す: この RUN は root の層で `USER node` より前に置き、`/home/node/.config` が symlink のとき、`/home/node/.config/c3c` が既にあるときはビルドを止める（層 2 が位置を確かめる）。

- [ ] **Step 7: README を直す**

- 「## GitHub トークンの配線」の `SECRETS_DIR` の手順: 1 つ目の文として、コンテナの中の `~/.config` は node がディレクトリを作れる（ブラウザや gh などの設定）が、`~/.config/c3c` は node が改名も削除もできない、と書く。2 つ目の文として、#275 より前のイメージでは `~/.config` に書けないので `-b` で作り直す、と書く。
- 「## 変更後の確認」に 1 段落: `Dockerfile.claude` の `~/.config` の RUN（#275）を変えた場合は、`./test-build.sh --validator-only`、`./test-build.sh --build-only`、`./test-build.sh --config-ro-only`、`bash tests/test-runtime.sh` を走らせる。
- Copilot の受け入れの段落の「`/home/node/.config` には node が新しいディレクトリを作れないので、gh の設定の場所には目印を置けない。」を、「gh の設定の場所には目印を置かず、」に直す。canary（`tests/copilot-canary.sh`）は変えない。
- README の「セキュリティモデル」節に残余の一覧があれば、`~/.config` そのものの改名は防がないことを 1 行足す。無ければ足さない。

- [ ] **Step 8: lint と commit**

Run: `./lint.sh` → Expected: rc 0、警告ゼロ（Markdown のアンカーの検査を含む）。

```bash
git add Dockerfile.claude test-build.sh docs/development-invariants.md README.md
git commit -m "fix: ~/.config を sticky にして node が書けるようにする（#275）"
```

### Task 2: 実機の確かめ・PR 前レビュー・PR

- [ ] **Step 1: `--check` がドリフトを出すことを確かめる（イメージを作り直す前）**

ホストで、変更前にビルドした findsummits のイメージがある状態で、このブランチの `c3c` で `./c3c --check <findsummits の checkout>` を走らせる。
Expected: 境界アセットのドリフトの WARNING（`Dockerfile.claude` が変わった）が出て、結果が `WARN`。

- [ ] **Step 2: findsummits の実機で確かめる**

findsummits のイメージを作り直すのは持ち主の判断なので、先に持ち主に聞く。許可が出たら、このブランチの `c3c` で `c3c claude -b`（findsummits の根で）を走らせる。次に対話のコンテナの中で、`XDG_CONFIG_HOME` を設定せずに、findsummits の `docs/decisions/research/browser-automation-probe.md` の「## やり直すとき」の 3 コマンドをリポジトリの根で走らせる。

```bash
node docs/decisions/research/browser-automation-probe/cdp_probe.js google-chrome "$(mktemp -d)"
node docs/decisions/research/browser-automation-probe/cdp_probe.js brave-browser "$(mktemp -d)"
node docs/decisions/research/browser-automation-probe/bidi_probe.js /usr/lib/firefox/firefox "$(mktemp -d)"
```

3 コマンドの前に `env | grep '^XDG_'` を走らせ、出力が空であることを確かめる（空でなければ出た行を控え、`unset` してから 3 コマンドを走らせる。書き込み先を別の場所へ逸らす変数があると、`~/.config` に書けることを確かめたことにならないため）。
Expected: 3 つとも rc 0。あわせて `stat -c %u:%g:%a ~/.config ~/.config/c3c` が `0:0:1777` と `0:0:755`。走らせられなければ `not run` と理由を書く。

- [ ] **Step 3: 完了前の確認**

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

`./lint.sh`、`./test-build.sh --validator-only`、`./test-build.sh --launcher-only`、`./test-build.sh --build-only`、`./test-build.sh --config-ro-only`、`bash tests/test-runtime.sh`、Step 1・2 の結果を、実行したもの・`not run` のものに分けて控える。

- [ ] **Step 4: PR 前の二重レビュー（区分が境界のため）**

**REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review

Claude（`claude-review` skill）→ Codex（`codex-review` skill、`--provider openai -m gpt-6.1-sol`）の順で background で起動する。Critical・Important を直して確認限定巡を終える。並走（Fusion）は今は PR 前では走らせない。

- [ ] **Step 5: PR を作る**

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:finishing-a-development-branch

Step 4 で変えた範囲に当たる検証（Step 3 の一覧のうち、変えたファイルに関わるもの）を走らせ直す。変更が無ければ走らせ直さない。push は持ち主に確かめてから行う。PR 本文には次を書く。
- `Closes #275`
- 判定と未対応の Minor
- `not run` の理由
- 計画レビューを `docs/superpowers/plans/` の計画に記録したこと

両レビューの全文は PR コメントに投稿する。PR 後のレビューとマージは、作成に関わっていない対話セッションに handover で渡す。マージの後に、SemVer の判定（既定の挙動の修正なのでパッチ）を添えてタグを提案する。

---

## 計画レビューの記録

- Self-Review: 検証式の引数の記述（`set`/`unset` → `image`・`set`・`unset`）を修正
- 版: `plan-initial.md` （非公開の記録に保存）
- Claude（claude-opus-5-5、session `fcbdf2f5-ecca-4e1a-a609-7f52802f762b`、所要 242 秒）: 修正後に渡せる。生の出力 （非公開の記録に保存）
  - I1 `CONFIG_DIR_PROBE` を `--config-ro-only` の分岐より後ろに置くと空で PASS する → 採用（`run_config_ro_tests()` の直前に定義、Step 3 に空の評価への注意）
  - I2 `~/.config` そのものは node が改名・移動できる → 実測で確認（今も同じ親の中で改名でき、変更後は別の親へも移せる）。持ち主の判断で既知の限界として書く（Task 0 Step 3、Task 1 Step 6・7、Global Constraints）
  - I3 ブランチを作る Step と using-git-worktrees が無く、設計が未追跡 → 採用（Task 0）
  - I4 推奨実装の理由が判定順 2 に当たる → 採用（末尾の行を書き直し）
  - I5 タグの前の `--check` の実機確認が無い → 採用（Task 2 Step 1）
  - M1 `TEST_RUNTIME_USERNS=1` の実行が無い → 採用（Task 1 Step 5）
  - M2 CI で守られない → 採用（層 2 の静的検査）
  - M3 アサーションの RUN が root の層の最後でなくなる → 採用（新しい RUN をアサーションの前に置く）
  - M4 README の見出しと findsummits の資料の場所 → 採用
  - M5 未設定の組を `env -u`、判定を `[ -c ]` に → 採用
  - M6 `--build-only` の後に `--config-ro-only` → 採用
  - M7 独自のベースで image の probe が崩れる → 採用（コメントで注記）
- Codex（gpt-6.1-sol、所要 141 秒）: 修正後に渡せる。生の出力 （非公開の記録に保存）
  - I1 `.config` そのものの改名が検証から抜けている → Claude I2 と同じ扱い（実測、持ち主の判断で既知の限界）
  - I2 未設定の組が呼び出し元の `SECRETS_DIR` を継承する → 採用（`env -u SECRETS_DIR`、設定ありの組はダミーの秘密だけ）
  - I3 runtime userns の構成を走らせるコマンドが無い → 採用（Claude M1 と同じ）
  - I4 挙動の変更と README が別の commit → 採用（Task 1 の 1 つの commit にまとめた）
  - I5 findsummits の資料の場所と 3 コマンドが無い → 採用（Task 2 Step 2 にパスと 3 コマンド）
  - M1 ブランチの Step と using-git-worktrees → 採用（Claude I3 と同じ）
  - M2 PR 前レビューの後の再検証 → 採用（Task 2 Step 5）
  - M3 RED の Expected のモードの誤記 → 採用（「`0:0:1777` でない」）
- 確認限定巡 1: Codex（I1〜I5、所要 27 秒）→ すべて直った、実装に渡せる。生の出力 （非公開の記録に保存）
- 確認限定巡 1: Claude（I1〜I5、所要 17 秒）→ すべて直った、実装に渡せる。生の出力 （非公開の記録に保存）
- 確認限定巡 2: Codex（fusion の I3・I5 後半・I7、所要 26 秒）→ I3・I5 後半は直った。I7 は `XDG_` の出力が空であることまで求めていない → 反映（出力が空であること、空でなければ控えて `unset`）。生の出力 （非公開の記録に保存）
- 確認限定巡 3: Codex（fusion の I7、所要 26 秒）→ 直った、実装に渡せる。生の出力 （非公開の記録に保存）
- fusion（並走、正式外）: 修正後に渡せる。依頼した段階 high・実際の段階 standard（pattern cascade、ruleId `default`、degradedReason なし）、起動し直しなし、82.98 クレジット、所要 370 秒。承認の後に、初回の版（plan-initial）を公開の経路（`-c 3e039c5`、GitHub にある commit なので `--unpushed` なし、`-D docs/superpowers/plans/2026-11-17-config-dir-writable-275.md`）で送った。生の出力 `pairing-runs/20261117-c3c-plan-275-fusion/final.md`。Sol と材料が違った点: 設計の文書（未追跡）、グローバル `AGENTS.md`、`.claude/AGENTS.md` は送る root に無いので名前だけ（スキルの表の 2 列は貼った）、計画の写しの置き換えは 0 件
  - I1 挙動の変更と README が別の commit → Codex I4 と同じ（反映済み）
  - I2 未設定の組が呼び出し元の `SECRETS_DIR` を継承する → Codex I2 と同じ（反映済み）
  - I3 userns の構成は `bash tests/test-runtime.sh` で回す → 採用（並走だけ。Review Focus 3、Task 1 Step 5、Step 7 の README、Task 2 Step 3 を `tests/test-runtime.sh` に替えた）
  - I4 PR 直前の最終検証 → Codex M2 と同じ（反映済み）
  - I5 ブランチの Step → Claude I3 と同じ（反映済み）。想定外の失敗の扱い → 採用（並走だけ。Task 1 Step 3・5 に systematic-debugging）
  - I6 タグの前の `--check` → Claude I5 と同じ（反映済み）
  - I7 実機の 3 コマンドと前提 → Codex I5 と同じ（反映済み）。`env | grep '^XDG_'` の確認 → 採用（並走だけ。Task 2 Step 2）
  - M1 RED の Expected の誤記 → Codex M3 と同じ（反映済み）
  - M2 検証式の置き場と POSIX sh → 置き場は Claude I1 と同じ（反映済み）、POSIX sh → 採用
  - M3 `ls -A` が `c3c` だけの判定が脆い → 採用（`probe-275` が残っていないことだけを見る）
  - M4 不変条件の `Dockerfile.claude` の節にも書く → 採用（Task 1 Step 6）
  - M5 Step 2 の後の lint → 採用

区分: 境界（秘密のマウントの親ディレクトリの所有者とモードを変え、Copilot の sandbox がパスで隠す秘密の守りに関わるため）
推奨実装: Opus（判定順 2〈秘密やトークンを読む経路に触れる変更 → Claude（Opus）〉に当たる。判定順 4〈ホストでしか成立しない → Codex〉より先に当たる。ホストの Podman での `test-build.sh` の実ビルドと findsummits の実機確認は、ホストの Claude のセッションで回せる）
実装: Opus（持ち主指定、2026-11-17。計画者のセッションで続けず、handover で新しいセッションへ渡す）
