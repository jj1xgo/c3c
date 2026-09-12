# テストの検出力の追随（#59 台帳の隔離、#65 全体実行の終了コード、#70 hook テストの判定、#71 hook の fail-safe）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `test-build.sh` の全体実行を「緑と赤が終了コードで分かり、実台帳を汚さない」状態にし、同梱 hook の回帰テストが deny 応答の中身と jq 不在の fail-safe 経路を実際に検証するようにする。その検証で見つかった hook 本体の fail-safe の欠陥（#71）も同じ PR で直す。

**Architecture:** `test-build.sh` は、env 非混入テストの実ランチャー起動を他のランチャーテストと同じ `env -i HOME=<一時領域>` 隔離に変え（#59）、4 か所に複製されている「結果 3 行と exit」を関数 `finish_by_result` にまとめて全体実行もそれを呼ぶ（#65）。`examples/hooks/tests/test-block-pr-approve.sh` は `run_case` を stdout・stderr・終了コードを別々に取る判定に書き換え、C10 は hook が使う外部コマンドだけを symlink した shim ディレクトリを PATH にして起動する（#70）。`examples/hooks/block-pr-approve.sh` の jq 不在分岐は、生 JSON の引用符を空白に置き換えてから既存の判定にかける（#71）。`ci.yml`・README・ランチャー本体は変更しない。

**Tech Stack:** bash、jq、shellcheck 0.11.0、podman 5.8（全体実行の検証にだけ使う）、`gh` CLI。

**Spec:** この文書の「設計」節と Issue #59、#65、#70、#71。設計の合意は 2026-09-12 の Fable セッション（brainstorming）で持ち主が承認した。

**実装: Opus（このセッションで `/model` を切り替える）。** 理由: hook 本体（`examples/hooks/block-pr-approve.sh`）の改修を含むため、CLAUDE.md「モデルと実装者の使い分け」の 2 が先に当たる。#59・#65・#70 だけなら 4 で Codex だったが、持ち主が「1 つの PR で hook 修正も含め、実装は Opus」を選んだ。

## Global Constraints

- commit メッセージ、PR の題名と本文、PR コメント、スクリプトのコメントとメッセージは日本語のみ（README「表記」節）。`[PASS]`・`[FAIL]`・`ok   - `・`FAIL - `・「全ケース green」などテストや CI が照合する機械可読トークンは変えない。
- commit の型は `fix:`、`test:`、`docs:` の接頭辞＋日本語の要約。
- すべての `gh` コマンドに `-R jj1xgo/claude-container` を付ける（この checkout の既定 repo は upstream を指す）。
- hook のトリガー文字列（承認系のサブコマンド）を、シェルのコマンド行・commit メッセージ・PR 本文の見出しに素の平文で書かない。単引用符で囲んだリテラル（`jq -n --arg c '...'` の引数など）は稼働中の hook が引用文字列として除去するので可（Task 3 の probe はこの形）。テストの入力をコマンド行へ展開せず、テストスクリプト（`/tmp` のコピーを含む）の実行とそのパイプだけにする。変異注入は `sed` / `python3` のスクリプト内で行う。テストファイルの全文置換（Task 4 Step 1）は Bash のヒアドキュメントではなく Write ツールで行う。
- `lint.sh` が通ること（`bash -n` と shellcheck 0.11.0、compose 検証）。

---

## 設計

### 調査で確定した事実（2026-09-12、main の abde4e8、host で実測）

- `test-build.sh:1158` の env 非混入テストは `PATH=... "${SCRIPT_DIR}/claude-container" "$ENV_PROJECT_DIR"` を `env -i` なしで起動し、`record_project_in_ledger()`（`claude-container:197`）が実ユーザーの `$HOME/.local/state/claude-container/projects` に一時パスを 1 行追記する。同じ起動を `env -i HOME="$ENV_TESTROOT" PATH="$ENV_TESTROOT/bin:$PATH"` に変えると、台帳は `$ENV_TESTROOT/.local/state/claude-container/projects` に書かれ（`grep -qxF` で一致）、実台帳の sha256 は前後で同じ。env 非混入の check は引き続き PASS。
- `test-build.sh` の「結果 3 行と exit」は `--validator-only`・`--config-ro-only`・`--launcher-only` の 3 か所で同一の 7 行、全体実行の末尾（1180 行以降）は結果 3 行の後に手動確認の案内を出して exit せず終わる（終了コードは最後の `log` の 0）。3 か所を関数 `finish_by_result` に置き換え、全体実行の末尾で案内の後に同関数を呼ぶ形を `git archive` のコピーで試し、`bash -n`・shellcheck 成功、`--launcher-only` PASS=75 rc=0、`--validator-only` PASS=82 rc=0、ランチャー期待値を改変すると PASS=74 / FAIL=1 rc=1。
- `examples/hooks/tests/test-block-pr-approve.sh` の `run_case` は「stdout と stderr を合流した出力が非空＝deny」で判定する。hook のコピーで deny 応答を allow に置換しても全ケース green（rc=0）。C10 の `NOJQ_PATH` は jq と同居する `/usr/bin` を丸ごと落とすので `bash` 自体が見つからず（rc=127）、その stderr を deny と誤判定する。
- 新しい判定（rc・stdout の JSON・stderr を分離）と shim PATH（`type -P` で解決した bash・cat・grep・sed・awk の symlink）で C10 を回すと、**現行の hook は rc=0・無出力で「pass」になり FAIL する**。`bash -x` で追うと、jq 不在分岐は `cmd=$input` で生 JSON をそのまま判定にかけるため、`--approve"`（直後が JSON の閉じ引用符）が承認フラグの正規表現 `(^|[[:space:]])(--approve([[:space:]]|$)|...)` に当たらない。整形 JSON でも 1 行 JSON でも同じ。これが #71。
- #71 の修正候補（jq 不在分岐で `\"`・`"` と `\n`・`\t`・`\r` のエスケープを空白に置換してから判定）を hook のコピーに当て、shim PATH で deny 期待 6 ケース（`--approve`、`-a 123`、`--approve --body`、`event=APPROVE` の引用なし・あり、ヒアストリング併用）がすべて deny、`--comment`・`--request-changes` は無出力。`git commit -am "...gh pr review --approve..."` は jq 不在では deny（偽陽性側。引用文字列の除去に jq が要るため。hook 自身のコメントが安全方向としている挙動と一致）。通常経路は新テストで 15 ケース green、shellcheck 成功。引用符だけを置換する案は、command 値の `--approve` の直後に改行やタブが続く形（JSON では `--approve\necho`）を通してしまうことを Codex の計画レビューが静的に指摘し、host で再現した（`\n`・`\t`・`\r` も置換する案では deny）。
- 新テストの変異検出: 修正済み hook のコピーで deny を allow に置換すると「10 件 FAIL」、shim から bash を除くと C10 が `rc=127` で FAIL。
- host に podman 5.8.6 と `localhost/claude-test` イメージがある。実台帳は 4 行。
- Codex の計画レビューが静的に指摘し host で再現した別件: 通常経路（jq あり）でも `gh pr review 1 --approve;` のように承認フラグの直後に `;`・`&&`・`|`・`)` が続くと deny しない（終端を空白か行末に限定しているため）。#72 として起票し、この計画の範囲外。

### 変更

1. `test-build.sh` env 非混入テスト: 起動を `env -i HOME="$ENV_TESTROOT" PATH="$ENV_TESTROOT/bin:$PATH"` に変え、台帳が隔離 HOME に書かれたことを `check` 1 件で確かめる（#59）。
2. `test-build.sh`: 関数 `finish_by_result` を層 1 の関数定義の前に置き、3 サブモードと全体実行の末尾から呼ぶ。全体実行では手動確認の案内を結果 3 行の前に移し、結果 3 行がログの最後になる（#65。出力順の変更は意図したもの）。
3. `examples/hooks/block-pr-approve.sh` jq 不在分岐: `cmd=$(printf '%s' "$input" | sed -E 's/\\["ntr]/ /g; s/"/ /g')`、`stripped_hd=$cmd`（#71）。
4. `examples/hooks/tests/test-block-pr-approve.sh`: 全文を Task 4 の内容に置き換える（#70）。出力形式（`ok   - `、`FAIL - `、「全ケース green」、「N 件 FAIL」）は維持。

### 捨てた案と理由

- 全体実行の末尾に `[ "$FAIL" -eq 0 ] || exit 1` を 1 行足すだけ: 4 か所の複製が残り、サブモードで実証した赤の挙動が全体実行に及ぶ保証が構造にならない。関数化で「赤はサブモードで実証、全体実行は緑 1 回」の検証方針が成り立つ。
- #70 の変異確認をテストスクリプトに常設する: 持ち主が「計画の検証手順として 1 回実測」を選択。テストは判定方式の修正と C10 の shim 化に絞る。
- #71 を別 PR にする: #70 の新判定で C10 が #71 を赤にするため、同じ PR で直さないと CI が緑にならない。持ち主が 1 PR・Opus 実装を選択。
- jq 不在時に「承認らしき語を含めば拒否」の緩い判定に変える: 既存の判定を活かす引用符・エスケープの置換の方が変更が小さく、通常経路と同じ正規表現を通る。
- 引用符だけを置換する（最初の候補）: `--approve` の直後に `\n` などのエスケープが続く command を通す。実測で確認し、エスケープも置換する形にした。
- #59 の回帰テストを「実台帳の sha256 が前後で同じ」にする: 実台帳に依存し、CI や別環境で意味が変わる。隔離台帳への正の検査にした。
- PR 作成前に `claude-review` skill で Claude のレビューを受ける（Codex の計画レビューの should-fix）: その手順は Codex が実装するときの規則（`~/.codex/AGENTS.md`）。実装者が Claude（Opus）の今回は、独立レビューは PR 後の新しい Fable セッションと Codex が担う（CLAUDE.md「モデルと実装者の使い分け」）。
- テストの deny 判定を `jq -r` の抽出値だけで行う（最初の案）: stdout に deny の JSON と余分な断片が続いても deny と判定する（Codex の指摘、host で再現）。`jq -es` で「単一の JSON オブジェクトで permissionDecision が deny」を要求する形にした。

### 合格条件

- `./test-build.sh --launcher-only` PASS=75 / FAIL=0 rc=0、`--validator-only` PASS=82 / FAIL=0 rc=0。ランチャーの期待値を 1 件改変すると `--launcher-only` が rc=1。
- `./test-build.sh`（全体実行、host、実 podman）が FAIL=0 で rc=0。結果 3 行がログの最後。実行前後で `~/.local/state/claude-container/projects` の sha256 が同じ。「起動台帳の記録が隔離 HOME に閉じる」が `[PASS]`。
- `bash examples/hooks/tests/test-block-pr-approve.sh` が 15 ケース ok・「全ケース green」rc=0。修正前の hook（`git show abde4e8:examples/hooks/block-pr-approve.sh`）に対しては C10 が FAIL。deny を allow に置換した hook では FAIL が 1 件以上。shim から bash を除くと C10 が FAIL。
- `./lint.sh` 成功。
- PR の CI が緑（hook ステップに「全ケース green」）。
- PR 本文が最終状態（検証結果、not run、Closes #59 #65 #70 #71）で ready。

## 実行者への前提

- 実行者はこのセッションの Claude（Opus）。最初の編集の前に、持ち主が `/model` ピッカーで Opus を選び `s`（このセッションだけ）で切り替える。Claude は切替を要求して待つだけで、自分では切り替えない。
- 作業ブランチは `fix/test-detection-59-65-70-71`（main の abde4e8 から切り、この計画がコミット済み）。この checkout は 1 つだけで、他の worktree は無い。
- **PR のマージは行わない。** Task 6（実行結果の記録と handover）まで進めて止まる。レビューは新しい Fable セッション（Fable と Codex の二重）、マージは持ち主。
- 書き込みを伴う外部操作は次に限る: `git push`、`gh pr create --draft`・`gh pr edit`・`gh pr ready`・`gh pr comment`（本 PR）、差分外の指摘が出たときの `gh issue create --label bug --label priority-low`（本文に根拠と実測を書く）。読み取りの `git fetch`、`gh run list/watch/view`、`gh pr view`、`gh issue view` は制限しない。
- `./test-build.sh` の全体実行は Task 2 の Step 6 で行う（Task 1 の #59 修正が入った後）。通常は 1 回。FAIL が出たときだけ Step 6 の手順に従って再実行する。それ以外はサブモードだけを使う。全体実行は実 podman build を含み数分かかる。
- hook のトリガー文字列をコマンド行に書かない（Global Constraints）。テストの実行は 1 コマンド、変異は下記のスクリプトで行う。
- CI は `pull_request` と main への push で走り、作業ブランチへの push だけでは走らない。最初の push の直後に本 PR を draft で作り、以降の CI 待ちはその PR の run を見る。CI の完了待ちは commit 単位で、run の `conclusion` と失敗ステップ名で判定する:

  ```bash
  sha=$(git rev-parse HEAD); id=""
  for i in $(seq 1 20); do
    id=$(gh run list -R jj1xgo/claude-container --commit "$sha" --json databaseId,workflowName -q '[.[] | select(.workflowName == "CI")][0].databaseId')
    [ -n "$id" ] && break
    sleep 15
  done
  if [ -z "$id" ]; then echo "判定不能: 5 分待っても run が登録されない"; else
    echo "run=$id  https://github.com/jj1xgo/claude-container/actions/runs/$id"
    gh run watch -R jj1xgo/claude-container "$id" >/dev/null 2>&1
    gh run view -R jj1xgo/claude-container "$id" --json status,conclusion --jq '"status=" + .status + " conclusion=" + .conclusion'
    echo "失敗したステップ:"; gh run view -R jj1xgo/claude-container "$id" --json jobs --jq '.jobs[].steps[] | select(.conclusion=="failure") | .name'
  fi
  ```
  `conclusion=success` なら緑。`failure` なら赤で失敗ステップ名を読む。`status` が `completed` 以外か `id` が空なら判定不能として再実行する。ログは `gh run view -R jj1xgo/claude-container "$id" --log`。
- `<本 PR の番号>`、`<sha>`、`<run の URL>` は実行時に埋める値。

---

### Task 0: ブランチを切り、モデルを切り替える

**Files:** なし

- [x] **Step 1: 作業ツリーがきれいで origin/main の先頭を確かめる**

Run:
```bash
git status --short --branch
git fetch origin && git log --oneline -1 origin/main
```
Expected: `## fix/test-detection-59-65-70-71` で未コミットの差分なし。origin/main は `abde4e8` かそれ以降。

- [x] **Step 2: 作業ブランチにいることを確かめる**

ブランチ `fix/test-detection-59-65-70-71` はこの計画を commit したときに作成済み。
```bash
git branch --show-current
```
Expected: `fix/test-detection-59-65-70-71`。違えば `git switch fix/test-detection-59-65-70-71`。

- [x] **Step 3: モデルの切替を要求して待つ**

持ち主に「`/model` で Opus を選び `s` で切り替えてください」と伝え、切り替わるまで編集しない。

---

### Task 1: env 非混入テストを隔離し、台帳が隔離 HOME に閉じることを検査する（#59）

**Files:**
- Modify: `test-build.sh:1158`（起動行）、`test-build.sh:1170` の直前（check の追加）

**Interfaces:**
- Produces: check 名 `起動台帳の記録が隔離 HOME に閉じる`。Task 2 Step 6 の全体実行でこの名前を照合する。

- [x] **Step 1: 対象行が 1 か所ずつあることを確かめる**

Run:
```bash
grep -cF 'PATH="$ENV_TESTROOT/bin:$PATH" "${SCRIPT_DIR}/claude-container" "$ENV_PROJECT_DIR" >/dev/null 2>&1' test-build.sh
grep -cxF 'rm -rf "$ENV_TESTROOT"' test-build.sh
```
Expected: どちらも `1`（この host の Bash ツールでは `grep` が ugrep を包む関数なので、`$` や `{}` を含むパターンは `-F` の固定文字列で照合する）。

- [x] **Step 2: 置換する**

```bash
python3 - <<'EOF'
p="test-build.sh"; s=open(p).read()
old1='PATH="$ENV_TESTROOT/bin:$PATH" "${SCRIPT_DIR}/claude-container" "$ENV_PROJECT_DIR" >/dev/null 2>&1\n'
new1='# 他のランチャーテストと同じく env -i で隔離する。隔離しないと record_project_in_ledger() が\n# 実ユーザーの $HOME の起動台帳に一時パスを 1 行残す（claude-container#59）。\nenv -i HOME="$ENV_TESTROOT" PATH="$ENV_TESTROOT/bin:$PATH" "${SCRIPT_DIR}/claude-container" "$ENV_PROJECT_DIR" >/dev/null 2>&1\n'
old2='rm -rf "$ENV_TESTROOT"\nlog ""\n'
new2='# 起動台帳は隔離 HOME 側に書かれ、実台帳（実ユーザーの ~/.local/state）には触れない（claude-container#59）\ncheck "起動台帳の記録が隔離 HOME に閉じる" grep -qxF -- "$ENV_PROJECT_DIR" "$ENV_TESTROOT/.local/state/claude-container/projects"\n\nrm -rf "$ENV_TESTROOT"\nlog ""\n'
assert s.count(old1)==1 and s.count(old2)==1
open(p,"w").write(s.replace(old1,new1).replace(old2,new2)); print("ok")
EOF
git diff --stat
```
Expected: `ok`、差分は `test-build.sh` のみ（追加 6 行、削除 1 行）。

- [x] **Step 3: 構文と lint を通す**

Run:
```bash
bash -n test-build.sh && echo "bash -n ok"
./lint.sh
```
Expected: `bash -n ok`、lint 成功（終了コード 0）。

- [x] **Step 4: 隔離起動を単独で実測する（全体実行を待たずに #59 の効果を見る）**

Run（test-build.sh の該当部分と同じ手順を手で回す）:
```bash
before=$(sha256sum ~/.local/state/claude-container/projects) || { echo "実台帳を読めない"; exit 1; }
T=$(mktemp -d) || exit 1; mkdir -p "$T/bin"
printf '#!/bin/bash\ncase "$1" in\n  image) [[ "$2" == "exists" ]] && exit 1 ;;\nesac\nexit 0\n' > "$T/bin/podman"; chmod +x "$T/bin/podman"
mkdir -p "$T/proj/.claude-container.d"; printf '[user]\n\tname = dummy\n' > "$T/dummy-gitconfig"
echo "GITCONFIG_FILE=$T/dummy-gitconfig" > "$T/proj/.claude-container.d/env"
ctx_before="$(ls -1 .build-context/ 2>/dev/null || true)"
env -i HOME="$T" PATH="$T/bin:$PATH" ./claude-container "$T/proj" >/dev/null 2>&1; echo "rc=$?"
ctx_after="$(ls -1 .build-context/ 2>/dev/null || true)"
grep -qxF -- "$T/proj" "$T/.local/state/claude-container/projects" && echo "隔離台帳に記録"
after=$(sha256sum ~/.local/state/claude-container/projects) || { echo "実台帳を読めない"; exit 1; }; [ "$before" = "$after" ] && echo "実台帳 不変"
for d in $(comm -13 <(echo "$ctx_before" | sort) <(echo "$ctx_after" | sort)); do rm -rf ".build-context/$d"; done; rm -rf "$T"
```
Expected: `rc=0`、`隔離台帳に記録`、`実台帳 不変`。この間、この host で別の `claude-container` を起動しない（`.build-context/` の差分で後始末するため）。

- [x] **Step 5: Commit**

```bash
git add test-build.sh
git commit -m "fix: env 非混入テストの実ランチャー起動を env -i で隔離し、起動台帳が隔離 HOME に閉じることを検査する（#59）"
```

---

### Task 2: 結果表示と終了コードを関数にまとめ、全体実行も FAIL で非 0 にする（#65）

**Files:**
- Modify: `test-build.sh`（3 サブモードの結果ブロック、層 1 の関数定義の直前、ファイル末尾）

**Interfaces:**
- Produces: 関数 `finish_by_result`（引数なし。結果 3 行を `log` し、`$FAIL` が 0 なら `exit 0`、それ以外は `exit 1`）。

- [x] **Step 1: 置換対象の個数を確かめる**

Run:
```bash
python3 - <<'EOF'
s=open("test-build.sh").read()
block='''  log "========================================"
  log "  結果: PASS=${PASS}  FAIL=${FAIL}"
  log "========================================"
  if [ "$FAIL" -eq 0 ]; then
    exit 0
  fi
  exit 1
'''
print("sub-mode blocks:", s.count(block))
print("layer1 marker:", s.count('# --- 層1: validate-build-input.sh のベクタ表・契約異常系テスト（claude-container#34） ---'))
print("tail ok:", s.endswith('log "  5. cat /tmp/test-claude-history/bash_history で履歴を確認"\n'))
EOF
```
Expected: `sub-mode blocks: 3`、`layer1 marker: 1`、`tail ok: True`。

- [x] **Step 2: 置換する**

```bash
python3 - <<'EOF'
p="test-build.sh"; s=open(p).read()
block='''  log "========================================"
  log "  結果: PASS=${PASS}  FAIL=${FAIL}"
  log "========================================"
  if [ "$FAIL" -eq 0 ]; then
    exit 0
  fi
  exit 1
'''
assert s.count(block)==3
s=s.replace(block,'  finish_by_result\n')
marker='# --- 層1: validate-build-input.sh のベクタ表・契約異常系テスト（claude-container#34） ---'
func='''# 結果の 3 行を出して FAIL 件数で終了コードを決める。サブモードと全体実行の両方から呼ぶ
# （claude-container#65: 全体実行だけ FAIL があっても 0 で終わっていた）。
finish_by_result() {
  log "========================================"
  log "  結果: PASS=${PASS}  FAIL=${FAIL}"
  log "========================================"
  if [ "$FAIL" -eq 0 ]; then
    exit 0
  fi
  exit 1
}

'''+marker
assert s.count(marker)==1
s=s.replace(marker,func,1)
tail='''log "========================================"
log "  結果: PASS=${PASS}  FAIL=${FAIL}"
log "========================================"
log ""
log "## bash history 永続化確認（手動）"
log "  以下を順番に実行してください："
log "  1. mkdir -p /tmp/test-claude-history"
log "  2. podman run --rm -it --userns=keep-id -v /tmp/test-claude-history:/workspace/.claude ${IMAGE} bash"
log "  3. コンテナ内で任意のコマンドを実行（例: ls, echo hello）"
log "  4. exit でコンテナを終了"
log "  5. cat /tmp/test-claude-history/bash_history で履歴を確認"
'''
assert s.count(tail)==1 and s.endswith(tail)
newtail='''log "## bash history 永続化確認（手動）"
log "  以下を順番に実行してください："
log "  1. mkdir -p /tmp/test-claude-history"
log "  2. podman run --rm -it --userns=keep-id -v /tmp/test-claude-history:/workspace/.claude ${IMAGE} bash"
log "  3. コンテナ内で任意のコマンドを実行（例: ls, echo hello）"
log "  4. exit でコンテナを終了"
log "  5. cat /tmp/test-claude-history/bash_history で履歴を確認"
log ""

finish_by_result
'''
s=s.replace(tail,newtail)
open(p,"w").write(s); print("ok")
EOF
grep -c 'finish_by_result' test-build.sh
bash -n test-build.sh && echo "bash -n ok"
./lint.sh
```
Expected: `ok`、`5`（定義 1 + 呼び出し 4）、`bash -n ok`、lint 成功。

- [x] **Step 3: サブモードの緑を確かめる**

Run:
```bash
./test-build.sh --launcher-only 2>/dev/null | grep '結果'; echo "rc=${PIPESTATUS[0]}"
./test-build.sh --validator-only 2>/dev/null | grep '結果'; echo "rc=${PIPESTATUS[0]}"
```
Expected: `結果: PASS=75  FAIL=0` と `rc=0`、`結果: PASS=82  FAIL=0` と `rc=0`。

- [x] **Step 4: Commit**

```bash
git add test-build.sh
git commit -m "fix: test-build.sh の結果表示と終了コードを finish_by_result にまとめ、全体実行も FAIL があれば 1 で終わる（#65）"
```

- [x] **Step 5: サブモードの赤を確かめる（期待値の改変と復元。commit の後に行うので `git checkout` で改変だけが消える）**

Run:
```bash
grep -c 'cfgx/.claude/hooks" -a' test-build.sh
sed -i 's|cfgx/.claude/hooks" -a|cfgx/.claude/hooks" -z|' test-build.sh
./test-build.sh --launcher-only 2>/dev/null | grep '結果'; echo "rc=${PIPESTATUS[0]}"
git checkout -- test-build.sh
git status --short
```
Expected: `1`、`結果: PASS=74  FAIL=1` と `rc=1`。`git status --short` は空（改変が消え、commit 済みの変更だけが残る）。

- [x] **Step 6: 全体実行を 1 回回す（#59 と #65 の実証）**

全体実行は複数の `podman build --no-cache` を含み、Bash ツールの前景上限（600 秒）を超えうる。次の 2 行を **`run_in_background: true` で起動し**、完了通知を待ってから後続の確認を行う（`sleep` での待機はしない）:
```bash
before=$(sha256sum ~/.local/state/claude-container/projects) || exit 1; echo "$before" > /tmp/test-build-ledger-before
./test-build.sh > /tmp/test-build-full.out 2>&1; echo "rc=$?" >> /tmp/test-build-full.out
```
完了通知の後に Run:
```bash
before=$(cat /tmp/test-build-ledger-before)
tail -5 /tmp/test-build-full.out
grep -E '起動台帳の記録が隔離 HOME に閉じる|結果:' /tmp/test-build-full.out
after=$(sha256sum ~/.local/state/claude-container/projects) || { echo "実台帳を読めない"; exit 1; }; [ -n "$before" ] && [ "$before" = "$after" ] && echo "実台帳 不変" || echo "実台帳 変化または取得失敗"
./claude-container --check 2>&1 | grep -c '/tmp/tmp\.'
```
Expected: `tail -5` の末尾が `====`・`結果: PASS=<N>  FAIL=0`・`====`・`rc=0`（案内より後に結果が出て、終了コードは 0）。`起動台帳の記録が隔離 HOME に閉じる` の行が `[PASS]`。`実台帳 不変`。`--check` の出力に `/tmp/tmp.` を含む行が `0`。PASS の件数 `<N>` を控える（Issue #59 の時点は 171、今回は Task 1 の check が 1 件増える）。FAIL が 0 でなければ、`/tmp/test-build-full.out` と `.claude/test-results/` の最新ログで原因を読み、この計画の変更が原因なら直して commit した後に再実行し、環境要因（ネットワーク等）なら原因を控えて再実行する。再実行の回数と理由は Task 6 の実行結果に書く。`/tmp/test-build-full.out` と `/tmp/test-build-ledger-before` は Task 6 の handover の後に削除する。

---

### Task 3: hook の jq 不在分岐で引用符を空白に置き換えてから判定する（#71）

**Files:**
- Modify: `examples/hooks/block-pr-approve.sh:103-105`

**Interfaces:**
- Produces: jq 不在時も `gh pr review <N> --approve` の形（command 値の末尾が承認フラグ）で deny の JSON（printf 版）を返す。Task 4 の C10 がこれを検査する。

- [x] **Step 1: 対象が 1 か所あることを確かめる**

Run:
```bash
python3 - <<'EOF'
s=open("examples/hooks/block-pr-approve.sh").read()
old='''  # jq 不在は環境異常。承認判定は生 JSON 文字列に対して継続する（fail-safe）。
  cmd=$input
  stripped_hd=$input
'''
print(s.count(old))
EOF
```
Expected: `1`。

- [x] **Step 2: 修正前の挙動を shim PATH で記録する（赤の確認）**

Run:
```bash
SHIM=/tmp/hook-shim; rm -rf "$SHIM"; mkdir -p "$SHIM" || exit 1
for c in bash cat grep sed awk; do ln -s "$(type -P "$c")" "$SHIM/$c" || exit 1; done; ls -l "$SHIM" | grep -c -- '->'
input=$(jq -n --arg c 'gh pr review 123 --approve' '{tool_input:{command:$c}}')
out=$(printf '%s' "$input" | PATH="$SHIM" bash examples/hooks/block-pr-approve.sh 2>&1); echo "rc=$? out=[${out}]"
```
Expected: `5`（symlink 5 本）、`rc=0 out=[]`（deny を出さずに通す。これが #71）。`$SHIM` は固定パスなので Step 4 は別の Bash 呼び出しでもよい。

- [x] **Step 3: 置換する**

```bash
python3 - <<'EOF'
p="examples/hooks/block-pr-approve.sh"; s=open(p).read()
old='''  # jq 不在は環境異常。承認判定は生 JSON 文字列に対して継続する（fail-safe）。
  cmd=$input
  stripped_hd=$input
'''
new='''  # jq 不在は環境異常。承認判定は生 JSON 文字列に対して継続する（fail-safe）。JSON の
  # 引用符（\\"、"）と改行・タブ・復帰のエスケープ（\\n、\\t、\\r）を空白に置き換えてから
  # 判定する。置き換えないと command 値の末尾が `--approve"` のように引用符で閉じられ、
  # または `--approve\\necho` のようにエスケープが続き、末尾を空白か行末に限定した判定に
  # 当たらない（claude-container#71）。引用文字列の除去はできないので、引用内の承認語は偽陽性側に
  # 倒れる。JSON の Unicode エスケープ（\\u0022 など）は復号しないので、その形の入力は検出しない。
  cmd=$(printf '%s' "$input" | sed -E 's/\\\\["ntr]/ /g; s/"/ /g')
  stripped_hd=$cmd
'''
assert s.count(old)==1
open(p,"w").write(s.replace(old,new)); print("ok")
EOF
sed -n '/jq 不在は環境異常/,/^fi$/p' examples/hooks/block-pr-approve.sh
```
Expected: `ok`。表示されるコードの行が `cmd=$(printf '%s' "$input" | sed -E 's/\\["ntr]/ /g; s/"/ /g')` と `stripped_hd=$cmd`（sed の式はバックスラッシュ 2 つ＋文字クラス `["ntr]`）。

- [x] **Step 4: 修正後の挙動を shim PATH で確かめる**

Run:
```bash
SHIM=/tmp/hook-shim
probe() { input=$(jq -n --arg c "$1" '{tool_input:{command:$c}}'); printf '%s' "$input" | PATH="$SHIM" bash examples/hooks/block-pr-approve.sh >/tmp/hook-shim-stdout 2>/tmp/hook-shim-stderr; rc=$?; d=$(jq -r '.hookSpecificOutput.permissionDecision // "none"' </tmp/hook-shim-stdout 2>/dev/null); printf 'rc=%s decision=%s stdout_bytes=%s stderr_bytes=%s :: %s\n' "$rc" "${d:-none}" "$(wc -c < /tmp/hook-shim-stdout)" "$(wc -c < /tmp/hook-shim-stderr)" "$1"; }
probe 'gh pr review 123 --approve'
probe 'gh pr review -a 123'
probe 'gh pr review 123 --approve --body "lgtm"'
probe 'gh api repos/o/r/pulls/1/reviews -f event=APPROVE'
probe 'gh api repos/o/r/pulls/1/reviews -f "event=APPROVE"'
probe 'gh pr review 1 --approve <<< "x"'
probe $'gh pr review 1 --approve\necho done'
probe $'gh pr review 1 --approve\tx'
probe 'gh pr review 123 --comment --body "note"'
probe 'gh pr review 123 --request-changes -b "fix"'
rm -rf "$SHIM" /tmp/hook-shim-stdout /tmp/hook-shim-stderr
```
Expected: 最初の 8 行が `decision=deny`（7・8 行目は command 値の中に改行・タブがあり、JSON では `\n`・`\t` のエスケープになる形）、最後の 2 行が `decision=none stdout_bytes=0 stderr_bytes=0`（無出力）、すべて `rc=0`。

- [x] **Step 5: 通常経路（jq あり）が変わっていないことと lint を確かめる**

Run:
```bash
bash examples/hooks/tests/test-block-pr-approve.sh | tail -2; echo "rc=${PIPESTATUS[0]}"
./lint.sh
```
Expected: 「全ケース green」`rc=0`（この時点のテストは旧判定だが、通常経路の 14 ケースの挙動が変わっていないことは確認できる）。lint 成功。

- [x] **Step 6: Commit**

```bash
git add examples/hooks/block-pr-approve.sh
git commit -m "fix: block-pr-approve.sh の jq 不在 fail-safe 経路で、生 JSON の引用符を空白に置き換えてから判定する（#71）"
```

---

### Task 4: hook 回帰テストの判定を応答の中身と終了コードで行い、C10 を shim PATH にする（#70）

**Files:**
- Modify: `examples/hooks/tests/test-block-pr-approve.sh`（全文を下の内容に置き換える）

**Interfaces:**
- Consumes: Task 3 の hook（jq 不在時に deny の JSON を返す）。
- Produces: 出力形式は従来どおり（`ok   - <desc>`、`FAIL - <desc> (...)`、末尾に「全ケース green」か「<n> 件 FAIL」）。`ci.yml` の hook ステップと README はそのまま。

- [x] **Step 1: 全文を置き換える**

`examples/hooks/tests/test-block-pr-approve.sh` を次の内容にする（既存ファイルを Write ツールで上書きする。Bash のヒアドキュメントでは書かない）:

```bash
#!/usr/bin/env bash
# test-block-pr-approve.sh — block-pr-approve.sh（issue #10/#17）の回帰テスト。
#
# 注意: トリガー文字列（gh pr review --approve 等）をこのファイル外のコマンド行
# （シェルのコマンド履歴・呼び出し元スクリプトの引数）に平文で書くと、稼働中の
# block-pr-approve.sh 自体に誤ブロックされうる。テストケースは必ずこのファイル内
# の変数として保持し、実行は「bash examples/hooks/tests/test-block-pr-approve.sh」
# のみで完結させること。
#
# 判定（claude-container#70）: hook の stdout・stderr・終了コードを別々に取り、
# deny 期待は「終了コード 0 かつ stdout が単一の JSON オブジェクトで permissionDecision が
# deny」、pass 期待は「終了コード 0 かつ stdout も stderr も空」を要求する。出力の有無だけで
# 判定すると、deny 応答が allow に変わる回帰や hook 自体の起動失敗を見逃す。
set -u

ROOT=$(cd "$(dirname "$0")/../../.." && pwd) || { echo "FAIL - 準備: ROOT を解決できない"; exit 1; }
HOOK="$ROOT/examples/hooks/block-pr-approve.sh"
[ -f "$HOOK" ] || { echo "FAIL - 準備: $HOOK が無い"; exit 1; }

TMPDIR_T=$(mktemp -d) || { echo "FAIL - 準備: mktemp -d に失敗"; exit 1; }
trap 'rm -rf "$TMPDIR_T"' EXIT

fail=0

# $1=説明 $2=期待("deny"|"pass") $3=コマンド文字列 [$4=hook 起動時の PATH（fail-safe 検証用）]
run_case() {
  desc="$1"
  expect="$2"
  cmdstr="$3"
  path_override="${4:-}"
  outfile="$TMPDIR_T/stdout"
  errfile="$TMPDIR_T/stderr"
  if ! input=$(jq -n --arg c "$cmdstr" '{tool_input:{command:$c}}'); then
    echo "FAIL - $desc (準備: 入力 JSON を生成できない)"
    fail=$((fail + 1))
    return
  fi
  if [ -n "$path_override" ]; then
    printf '%s' "$input" | PATH="$path_override" bash "$HOOK" >"$outfile" 2>"$errfile" && rc=0 || rc=$?
  else
    printf '%s' "$input" | bash "$HOOK" >"$outfile" 2>"$errfile" && rc=0 || rc=$?
  fi
  out=$(cat "$outfile")
  err=$(cat "$errfile")
  # stdout 全体が単一の JSON オブジェクトで、permissionDecision が deny か（jq -e: 真なら 0、偽なら 1、解析失敗は 2 以上）
  if printf '%s' "$out" | jq -es 'length == 1 and (.[0] | type == "object") and (.[0].hookSpecificOutput.permissionDecision == "deny")' >/dev/null 2>&1; then
    deny_json=1
  else
    deny_json=0
  fi
  if [ "$rc" -eq 0 ] && [ "$deny_json" -eq 1 ]; then
    actual="deny"
  elif [ "$rc" -eq 0 ] && [ ! -s "$outfile" ] && [ ! -s "$errfile" ]; then
    actual="pass"
  else
    actual="invalid"
  fi
  if [ "$actual" = "$expect" ]; then
    echo "ok   - $desc"
  else
    echo "FAIL - $desc (expected $expect, got $actual; rc=$rc stdout=${out:0:80} stderr=${err:0:80})"
    fail=$((fail + 1))
  fi
}

# --- DENY 期待 ---
run_case "C1 真正承認 --approve" deny 'gh pr review 123 --approve'
run_case "C2 真正承認 -a" deny 'gh pr review -a 123'
run_case "C3 真正承認 --approve --body" deny 'gh pr review 123 --approve --body "lgtm"'
run_case "C4 gh api unquoted event=APPROVE" deny 'gh api repos/o/r/pulls/1/reviews -f event=APPROVE'
run_case "C5 gh api quoted event=APPROVE (hardening)" deny 'gh api repos/o/r/pulls/1/reviews -f "event=APPROVE"'
run_case "C6 gh api --input - でJSON本文にAPPROVE (hardening)" deny "$(printf 'gh api repos/o/r/pulls/1/reviews --input - <<EOF\n{"event": "APPROVE"}\nEOF')"
run_case "C7 benign heredoc後に真正承認" deny "$(printf 'gh issue comment 1 --body-file - <<EOF\nsome text\nEOF\ngh pr review 1 --approve')"
run_case "C8 ヒアストリング併用の真正承認" deny 'gh pr review 1 --approve <<< "x"'
run_case "C9 残存FP許容: gh apiが実コマンドでheredoc本文に両パターン引用" deny \
  "$(printf 'gh api repos/o/r/issues/1/comments -f body=x --input - <<EOF\nplease see gh api pulls/2/reviews event=APPROVE for reference\nEOF')"

# --- pass 期待 ---
run_case "N1 issue17原再現 (single quote heredoc)" pass \
  "$(printf 'gh issue comment 17 --body-file - <<%s\n(quoted) gh pr review --approve\n%s' "'EOF'" "EOF")"
run_case "N2 gh pr comment heredocにgh api引用" pass \
  "$(printf 'gh pr comment 1 --body-file - <<EOF\ngh api pulls/1/reviews event=APPROVE\nEOF')"
run_case "N3 git commit -am 引用FP解消" pass 'git commit -am "docs: explain gh pr review --approve flow"'
run_case "N4 --comment" pass 'gh pr review 123 --comment --body "note"'
run_case "N5 --request-changes" pass 'gh pr review 123 --request-changes -b "fix"'

# --- fail-safe（jq不在） ---
# hook が使う外部コマンド（bash・cat・grep・sed・awk）だけを symlink した shim ディレクトリを
# PATH にする。PATH から jq のディレクトリを丸ごと落とす方式だと、usrmerge 環境では bash 自体が
# 消えて hook が起動せず、テストが空振りする（claude-container#70）。
SHIM="$TMPDIR_T/shim"
shim_ok=1
mkdir -p "$SHIM" || shim_ok=0
for c in bash cat grep sed awk; do
  if p=$(type -P "$c") && [ -n "$p" ] && ln -s "$p" "$SHIM/$c"; then
    :
  else
    echo "FAIL - C10 準備: $c を shim に置けない"
    fail=$((fail + 1))
    shim_ok=0
  fi
done
if [ "$shim_ok" -eq 1 ]; then
  run_case "C10 jq不在fail-safe: 真正承認は引き続きDENY" deny 'gh pr review 123 --approve' "$SHIM"
else
  echo "FAIL - C10 jq不在fail-safe: 準備に失敗したため未実行"
  fail=$((fail + 1))
fi

echo ''
if [ "$fail" -eq 0 ]; then
  echo "全ケース green"
  exit 0
else
  echo "$fail 件 FAIL"
  exit 1
fi
```

- [x] **Step 2: 15 ケース緑と lint を確かめる**

Run:
```bash
bash examples/hooks/tests/test-block-pr-approve.sh; echo "rc=$?"
./lint.sh
```
Expected: `ok   - ` が 15 行（C1〜C10、N1〜N5）、「全ケース green」、`rc=0`。lint 成功。

- [x] **Step 3: 新しい判定が #71 を検出することを確かめる（修正前の hook に対して C10 が赤）**

Run:
```bash
M=/tmp/hook-test-mut; rm -rf "$M"; mkdir -p "$M/examples/hooks/tests" || exit 1
git show abde4e8:examples/hooks/block-pr-approve.sh > "$M/examples/hooks/block-pr-approve.sh"
cp examples/hooks/tests/test-block-pr-approve.sh "$M/examples/hooks/tests/"
bash "$M/examples/hooks/tests/test-block-pr-approve.sh" | grep -E 'C10|件 FAIL|green'; echo "rc=${PIPESTATUS[0]}"
```
Expected: `FAIL - C10 ... (expected deny, got pass; rc=0 stdout= stderr=)`、`1 件 FAIL`、`rc=1`。修正前の hook は main の `abde4e8`（この計画の基準）に固定する。`$M` は固定パスなので Step 4・5 は別の Bash 呼び出しでもよい。

- [x] **Step 4: deny を allow に置換した hook で FAIL になることを確かめる**

Run:
```bash
M=/tmp/hook-test-mut
cp examples/hooks/block-pr-approve.sh "$M/examples/hooks/block-pr-approve.sh"
sed -i 's/permissionDecision:"deny"/permissionDecision:"allow"/; s/"permissionDecision":"deny"/"permissionDecision":"allow"/' "$M/examples/hooks/block-pr-approve.sh"
grep -c '"allow"' "$M/examples/hooks/block-pr-approve.sh"
bash "$M/examples/hooks/tests/test-block-pr-approve.sh" | tail -1; echo "rc=${PIPESTATUS[0]}"
```
Expected: `2`、`10 件 FAIL`、`rc=1`（deny 期待の C1〜C10 がすべて FAIL）。

- [x] **Step 5: shim から bash を除くと C10 が起動失敗として FAIL になることを確かめる**

Run:
```bash
M=/tmp/hook-test-mut
cp examples/hooks/block-pr-approve.sh "$M/examples/hooks/block-pr-approve.sh"
sed -i 's/for c in bash cat grep sed awk; do/for c in cat grep sed awk; do/' "$M/examples/hooks/tests/test-block-pr-approve.sh"
bash "$M/examples/hooks/tests/test-block-pr-approve.sh" | grep -E 'C10|件 FAIL'; echo "rc=${PIPESTATUS[0]}"
rm -rf "$M"
```
Expected: `FAIL - C10 ... (expected deny, got invalid; rc=127 stdout= stderr=...bash: command not found)`、`1 件 FAIL`、`rc=1`。

- [x] **Step 6: Commit**

```bash
git add examples/hooks/tests/test-block-pr-approve.sh
git commit -m "test: hook 回帰テストの判定を応答 JSON と終了コードで行い、jq 不在の C10 を shim PATH で起動する（#70）"
```

---

### Task 5: push、draft PR、CI、ready

**Files:** なし

- [x] **Step 1: push して draft PR を作る**

```bash
git push -u origin fix/test-detection-59-65-70-71
gh pr create -R jj1xgo/claude-container --draft --base main --head fix/test-detection-59-65-70-71 \
  --title 'fix: テストの検出力を上げる（台帳の隔離、全体実行の終了コード、hook テストの判定と fail-safe 修正）' \
  --body-file /tmp/pr-body.md
```
`/tmp/pr-body.md` は次の型で書き、Task 5 Step 3 で最終値に更新する:

```markdown
## 概要

`test-build.sh` の env 非混入テストを `env -i` で隔離し（#59）、結果表示と終了コードを `finish_by_result` にまとめて全体実行も FAIL で 1 を返す（#65）。同梱 hook の回帰テストは応答 JSON と終了コードで判定し、C10 は hook が使うコマンドだけの shim PATH で起動する（#70）。その C10 が検出した hook の jq 不在 fail-safe の欠陥を直した（#71）。

Closes #59
Closes #65
Closes #70
Closes #71

## 検証（host、2026-09-12）

- サブモード: `--launcher-only` PASS=75 / FAIL=0 rc=0、`--validator-only` PASS=82 / FAIL=0 rc=0。ランチャー期待値の改変で `--launcher-only` rc=1。
- 全体実行 <回数> 回（再実行があればその理由）: 最終の実行が PASS=<N> / FAIL=0 rc=0。結果 3 行がログの最後。実台帳の sha256 は前後で同じ。「起動台帳の記録が隔離 HOME に閉じる」PASS。`--check` に一時パス無し。
- hook テスト: 15 ケース green。修正前の hook で C10 が FAIL（#71 の検出）。deny を allow に置換した hook で 10 件 FAIL。shim から bash を除くと C10 が rc=127 で FAIL。
- hook の jq 不在経路: shim PATH で deny 期待 6 ケースが deny、`--comment`・`--request-changes` は無出力。
- `./lint.sh` 成功。
- CI: <sha> の <run の URL> が success。

## 意図した挙動の変更

- 全体実行の出力順: 手動確認の案内の後に結果 3 行が出る（結果が最後）。
- jq 不在時、引用文字列内の承認フラグ（`git commit -am "...--approve..."` など）は deny になる。引用文字列の除去に jq が要るため。偽陽性側で、hook のコメントが安全方向としている挙動。

## not run

- Actions 上での全体実行（実 podman が要るため CI 対象外、README のとおり）。
- runner での C10 の shim PATH の実測（CI の緑で代替）。

計画: `docs/superpowers/plans/2026-09-12-test-detection-followup.md`。マージは持ち主が行う。
```

- [x] **Step 2: CI の緑を確かめる**

「実行者への前提」の完了待ちを実行する（Bash ツールの `timeout` を 600000 にする。CI は 1〜2 分で終わる）。続けて:
```bash
gh run view -R jj1xgo/claude-container "$id" --log | grep -c '全ケース green'
gh run view -R jj1xgo/claude-container "$id" --json jobs --jq '.jobs[].steps[] | select(.name=="失敗時にテストログを出す") | .conclusion'
```
Expected: `conclusion=success`、`1`、`skipped`。

- [x] **Step 3: PR 本文を最終値に更新し、ready にする**

`/tmp/pr-body.md` の `<N>`・`<sha>`・`<run の URL>` を実測値に置き換えて:
```bash
gh pr edit -R jj1xgo/claude-container <本 PR の番号> --body-file /tmp/pr-body.md
gh pr ready -R jj1xgo/claude-container <本 PR の番号>
gh pr view -R jj1xgo/claude-container <本 PR の番号> --json isDraft,state,headRefOid -q '"\(.isDraft) \(.state) \(.headRefOid)"'
```
Expected: `false OPEN <HEAD の SHA>`。

---

### Task 6: 完了報告

- [x] **Step 1: 計画のチェック欄を更新し、実行結果を追記して commit する**

この計画のチェック欄を `[x]` にし、末尾に `## 実行結果（2026-09-12、Opus）` の節を足して次を書く: 本 PR の番号と URL、CI の最終状態（対象 commit の SHA と run の URL）、全体実行の PASS 件数、計画から外れた点、`not run` と理由、差分外で起票した Issue（あれば）。**Expected の文言を逐語で引用し、記録がどの合格条件を満たすかを対応づける。** commit して push し、「実行者への前提」の完了待ちでこの記録 commit の `conclusion=success` を確認する。確認できたら `gh pr edit` で PR 本文の「CI:」行を記録 commit の SHA と run に更新する。

- [x] **Step 2: handover を書く**

`handover` skill で引き継ぎを残す。**PR はマージしていない**こと、レビューは新しい Fable セッションで Fable と Codex の二重で行うことを明記する。

## 範囲外（Fable がレビュー時に行う）

- PR のレビュー（Fable と Codex の二重。Codex を先に background で起動する）。マージは持ち主。
- #72（承認フラグ直後の区切り文字で通常経路を迂回できる）は別 PR。修正時に回帰テストへ `--approve;` などの deny ケースを足す。
- jq 不在時の Unicode エスケープ（`\u0022` など）は復号しない。jq 不在は環境異常であり、この限界は hook のコメントに書く。
- #66・#67・#62 ほかの priority-low は対象外。

## Claude への受け渡し

**実装: Opus（このセッション）。** 理由: hook 本体の改修を含む（CLAUDE.md「モデルと実装者の使い分け」の 2）。持ち主が「1 つの PR で hook 修正も含め、実装は Opus」を選択（2026-09-12）。

手順: この計画を commit した後、持ち主が `/model` で Opus を選び `s` で切り替える。Opus は `superpowers:executing-plans` で Task 0 Step 1 から順に進め、Task 6 Step 2 の handover まで行って止まる。

---

## 実行結果（2026-09-12、Opus）

- 本 PR: [#73](https://github.com/jj1xgo/claude-container/pull/73)。`isDraft=false`、`state=OPEN`、HEAD `126103f5fb1946dc0428d574c1b72ee181f810c1`。マージしていない。
- 実装 commit: `02bc547`（#59）、`c3a5194`（#65）、`994f561`（#71）、`126103f`（#70）。
- CI: 最終 SHA `126103f5fb1946dc0428d574c1b72ee181f810c1` の [run 34673226802](https://github.com/jj1xgo/claude-container/actions/runs/34673226802) が `status=completed conclusion=success`、失敗ステップなし。ログの「全ケース green」が 1 件、`失敗時にテストログを出す` は `skipped`。この記録 commit の CI は push 後に別途確認し、PR 本文の「CI:」行へ反映する。

### 合格条件と実測の対応（Expected の文言を逐語で引用）

| 合格条件 | Expected（計画の逐語） | 実測 |
|---|---|---|
| サブモード緑 | `結果: PASS=75  FAIL=0` と `rc=0`、`結果: PASS=82  FAIL=0` と `rc=0` | Task 2 Step 3 で一致（`--launcher-only` PASS=75 / FAIL=0 rc=0、`--validator-only` PASS=82 / FAIL=0 rc=0） |
| ランチャー変異で赤 | `1`、`結果: PASS=74  FAIL=1` と `rc=1`。`git status --short` は空 | Task 2 Step 5 で一致。復元後の `git status --short` は空 |
| 全体実行 | `tail -5` の末尾が `====`・`結果: PASS=<N>  FAIL=0`・`====`・`rc=0`（案内より後に結果が出て、終了コードは 0） | 一致。`<N>` は **183**。`tail -12` で手動確認の案内の後に結果 3 行が出ることも確認 |
| 台帳の隔離 | `起動台帳の記録が隔離 HOME に閉じる` の行が `[PASS]`。`実台帳 不変`。`--check` の出力に `/tmp/tmp.` を含む行が `0` | 3 点すべて一致。実台帳は前後で 4 行・sha256 同一 |
| hook テスト 15 ケース | `ok   - ` が 15 行（C1〜C10、N1〜N5）、「全ケース green」、`rc=0` | 一致（`grep -c '^ok   - '` が 15） |
| 修正前 hook で C10 赤 | `FAIL - C10 ... (expected deny, got pass; rc=0 stdout= stderr=)`、`1 件 FAIL`、`rc=1` | `abde4e8` の hook で一致 |
| allow 変異で赤 | `2`、`10 件 FAIL`、`rc=1` | 一致 |
| shim から bash を除くと赤 | `FAIL - C10 ... (expected deny, got invalid; rc=127 stdout= stderr=...bash: command not found)`、`1 件 FAIL`、`rc=1` | 一致（stderr は `... 行 39: bash: co` まで表示、80 文字で切られる仕様どおり） |
| hook の jq 不在経路 | 最初の 8 行が `decision=deny`、最後の 2 行が `decision=none stdout_bytes=0 stderr_bytes=0`（無出力）、すべて `rc=0` | Task 3 Step 4 で一致。修正前は Task 3 Step 2 で `rc=0 out=[]`（#71 の再現） |
| lint | lint 成功（終了コード 0） | Task 1 Step 3、Task 2 Step 2、Task 3 Step 5、Task 4 Step 2 のすべてで `lint OK` rc=0（compose 検証込み） |
| PR の CI 緑 | `conclusion=success`、`1`、`skipped` | 一致（run 34673226802） |
| PR 本文が最終状態で ready | `false OPEN <HEAD の SHA>` | `false OPEN 126103f5fb1946dc0428d574c1b72ee181f810c1` |

### 計画から外れた点

- 全体実行の PASS 件数は **183**。計画の括弧は「Issue #59 の時点は 171、今回は Task 1 の check が 1 件増える」と見込んでいたが、#59 起票後に検査が増えている（validator の許可キー検査など）。FAIL=0 と rc=0 は合格条件どおりで、件数の見込み違いだけ。
- Task 3（hook の修正）を Task 2 Step 6 の全体実行の完了待ちと並行して実施した。`grep -c 'examples/hooks' test-build.sh` が `0`（全体実行は hook ファイルを参照しない）ことを先に確認したうえで並行させた。順序の入れ替えではなく、待ち時間の利用。
- 全体実行は 1 回のみ。再実行はしていない。

### not run

- Actions 上での全体実行（実 podman が要るため CI 対象外。README の「変更後の確認」節のとおり）。
- runner 上での C10 の shim PATH の実測（CI の緑で代替。host では実測済み）。
- jq 不在時の Unicode エスケープ（`\u0022` など）の復号は設計上行わない。範囲外として hook のコメントに明記した。
- #72（承認フラグ直後の区切り文字で通常経路を迂回できる）の修正は別 PR。

### 差分外で起票した Issue

なし（#71 と #72 は計画を書いた Fable セッションが起票済み）。

### 後始末

- `/tmp/test-build-full.out`、`/tmp/test-build-ledger-before`、`/tmp/pr-body.md` は handover の後に削除する。`/tmp/hook-shim`・`/tmp/hook-test-mut` は各 Step の末尾で削除済み。
