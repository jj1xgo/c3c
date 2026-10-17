# launcher テストの GitHub meta 取得をスタブにする（#213）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（Task 1 の前に読み込む。変更はテストコードだが、回帰の検査を先に書いて落ちることを確かめてから直す）

**Goal:** `test-build.sh --launcher-only` の launcher テストが、本物の `https://api.github.com/meta` に頼らずに通るようにし、CI の新しい checkout で通信が一時的に失敗しても落ちないようにする（jj1xgo/c3c#213）。

**Architecture:** `c3c -b` は `stage_build_context()`（`c3c` 2468〜2503 行）で `curl` を使って meta を取得し、失敗したときは前回のスナップショット、それも無ければ別プロジェクトのスナップショットを使う。どちらも無ければ `ERROR` で止まる。launcher のテストは、`launcher_sandbox_init`（`test-build.sh` 598〜649 行）が作る `$bin` を PATH の先頭に置いて動く。`curl` のスタブを、5 件ある `-b` のテストのうち 3 件だけが個別に `$bin/curl` へ置いていて、1341 行と 2121 行の 2 件は本物の `curl` を使っている。このスタブを `launcher_sandbox_init` に移し、呼び出しを記録させて、`-b` のテストがスタブを通ったことを検査で確かめる。

**Tech Stack:** bash（`test-build.sh`）、shellcheck（`./lint.sh`）

**Spec:** この計画の「## 背景と確認済みの原因」節（brainstorming で持ち主が 2026-10-17 に承認した、チャットでの小さな変更の仕様）

## 背景と確認済みの原因

- 2026-10-17 の #204 の CI（run 39019871090、attempt 1）で、2121 行の「build と run に共有・スキル・plugin・IPv6 の override が共存する」が 1 回だけ落ちた。再実行では通った。
- 再現（2026-10-17、コンテナ内、HEAD `b8fafd4`）: `git archive HEAD` で `.build-context` の無い展開を作り、常に rc 7 で失敗する `curl` を PATH の先頭に置いて `./test-build.sh --launcher-only` を実行した。結果、1341 行の「build と run の両方に override が渡る」と 2121 行のテストが落ち、ログには `ERROR: GitHub meta を取得できず、過去のスナップショットもありません。` が出た。ほかに落ちたのは「通信待ちの上限・再試行・スナップショット保護」（`tests/test_network_timeouts.py` などで本物の `curl` の動きを見るテスト）だけで、これは偽の `curl` に差し替えたことによる副作用。
- 同じ実験を `/workspace` で行うと 1341 行と 2121 行は PASS だった。`.build-context/` に別プロジェクトのスナップショットが残っていて、それで代わりにできたため。手元では通り、CI でだけ落ちる理由はこれで説明がつく。
- `c3c` が `curl` を呼ぶのは 2482 行の meta の取得だけ。launcher のサンドボックスを使うテストに、本物の meta の取得を前提にしたものは無い（`GitHub meta` を期待しているのは 2243〜2304 行のビルド用の関数と `tests/test_network_timeouts.py` で、どちらもサンドボックスを使わない）。
- 未確認: run 39019871090 の attempt 1 の CI ログに、実際に meta の `ERROR` が出ていたか。`ci.yml` は失敗時に `.claude/test-results/*.log` を出すが、ログの置き場（`productionresultssa0.blob.core.windows.net`）はコンテナの firewall で塞がれていて取れなかった。ホストで `gh run view 39019871090 -R jj1xgo/c3c --attempt 1 --log-failed | grep -n 'GitHub meta'` を実行すれば確かめられる（持ち主の任意の確認。結果が出ても、この計画の変更は変わらない）。

## Global Constraints

- 変更するファイルは `test-build.sh` だけ。`c3c`・`tests/*.py`・`.github/workflows/*` は変えない。
- 本物の `curl` の動きを確かめるテスト（`test-build.sh` 2243〜2304 行の関数、`tests/test_network_timeouts.py`）は変えない。
- 「失敗したときに `$out` を CI のログにも出す」（#213 の候補の 2 つ目）は入れない（`ci.yml` が失敗時にログを出すことは確認済み）。
- コメントと commit メッセージは日本語（README.md「表記」節）。
- 編集後は `./lint.sh` が rc 0。podman の無い環境（c3c のコンテナ内）では、`lint.sh` が自分で Compose 検証を飛ばし、`WARNING: podman が見つからないため compose config 検証をスキップしました` を出す。この WARNING と、shellcheck の版が CI の固定版と違うときの版の WARNING（README.md「変更後の確認」節で、コンテナ内では想定内とされている）だけは許す。ほかの WARNING は許さない。このとき Compose 検証は `not run`（理由: podman が無い）とし、PR の CI の `lint とビルド不要のテスト`（Compose 検証を含む）で確かめる。`LINT_SKIP_COMPOSE=1` は使わない（podman が無ければ要らない）。
- 公開側に置く計画の写しには、`~` 配下の個人設定のパス、レビューの session id と一時ファイルのパスを書かない（前例: `2026-10-17-codex-read-only-approval-207.md`）。計画レビューの生の出力は公開側に置かず、この計画の「計画レビューの記録」節を正本にする。
- `.c3c/allowed-domains.txt` の未コミットの `+api.typesafe.ai` の行（`/workspace` の main の作業ツリー）は触らない。作業は worktree で行う。

## Review Focus

1. 将来 `-b` のテストを足したとき、スタブを置き忘れても本物の通信に頼ってしまわないこと → スタブを `launcher_sandbox_init` に置けば、サンドボックスの中の全テストに掛かる（Task 1 Step 3）。
2. あるテストが `$bin/curl` を独自に置き換えた場合に、記録の検査が誤って通らないこと → 記録は `launcher_sandbox_reset_records` で消すので、前のテストの記録が残って誤って通ることはない（Task 1 Step 1・3）。
3. `--check` は meta を取得しない（`.build-context` を変えない）ので、スタブが置かれていても `--check` の無書き込みの検査（`snapshot_check_targets`）は変わらないこと → スタブと記録は `$root/bin` と `$root/curl-calls` にあり、`snapshot_check_targets` の対象（`$home`・`$proj`・`.build-context`）の外にある（Task 1 Step 4 の全件実行で確かめる）。
4. スタブが `--output` 以外の呼ばれ方をしたら成功にしないこと → 既存のスタブと同じく rc 2 を返す（Task 1 Step 3）。
5. 手元に `.build-context` のスナップショットがあると回帰を見落とすこと → worktree（`.build-context` に `github-meta*` が無い）で、失敗する `curl` を置いて確かめる（Task 1 Step 5）。

---

### Task 1: launcher のサンドボックスに meta 取得のスタブを置く

**Files:**
- Modify: `test-build.sh`
  - `launcher_sandbox_init`（598〜649 行）: `$bin/curl` のスタブを足す
  - `launcher_sandbox_reset_records`（654〜656 行）: `"$root/curl-calls"` も消す
  - 1341〜1343 行の check「build と run の両方に override が渡る」: 記録の検査を足す
  - 2121〜2125 行付近の check「build と run に共有・スキル・plugin・IPv6 の override が共存する」: 記録の検査を足す
  - 1695〜1707 行と 1993〜2005 行: 個別のスタブ（`cat > "$bin/curl" <<'CURL'` 〜 `chmod +x "$bin/curl"`）を消す。1992 行のコメント `# P2: -b では build・run の各呼び出しに export と override が 1 回ずつ渡る` は残す

**Interfaces:**
- Produces: `launcher_sandbox_init` の後、`$bin/curl` は実行可能なスタブ。呼ばれるたびに、引数を 1 行にして `"$root/curl-calls"` に追記する。引数に `--output <path>` があれば `<path>` に `{"web":[],"api":[],"git":[]}` を書いて rc 0、無ければ rc 2。`launcher_sandbox_reset_records` は `"$root/curl-calls"` を消す。

- [ ] **Step 0: 作業ツリーを作る**

**REQUIRED SUB-SKILL:** Use superpowers:using-git-worktrees

```bash
cd /workspace
git fetch origin
grep -qxF '.worktrees/' .git/info/exclude || printf '.worktrees/\n' >> .git/info/exclude
git worktree add -b fix/launcher-meta-stub-213 .worktrees/launcher-meta-stub-213 origin/main
cd /workspace/.worktrees/launcher-meta-stub-213
ls .build-context 2>&1
./test-build.sh --launcher-only 2>&1 | grep -E '\[FAIL\]|結果:'
```

Expected: worktree が `origin/main`（`b8fafd4` 以降）で作られ、`ls` は `No such file or directory`（スナップショットが無い = CI と同じ条件）。`--launcher-only` の `結果:` の行の PASS と FAIL の和を、check の総数 T として控える。この時点では 1341 行と 2121 行が本物の meta を取得するので、ネットワークが使えないとこの 2 件が FAIL になりうる（そのときも T は PASS と FAIL の和で決まる）。それ以外の FAIL が出たら、先へ進まずに止まって持ち主に報告する。以降の Step はこの worktree で行う。

- [ ] **Step 1: 落ちる検査を先に書く**

`launcher_sandbox_reset_records` の `rm -f` に `"$root/curl-calls"` を足す。1341 行と 2121 行の 2 つの check の検証式（`bash -c '...'`）に、`$2` が `$root` であることを使って `grep -qF 'https://api.github.com/meta' "$2/curl-calls"` を足す（「meta の取得がスタブを通った」を意味する。ファイルが無ければ grep は rc 2 で、検査は落ちる）。1341 行の式では、既存の `&&` の並びの末尾に `&&` でつなぐ。2121 行の式では、1 行目の `[ "$1" = 0 ] && [ "$(cat "$2/compose-calls")" = 2 ]` の後、`|| exit 1` の前に `&&` でつなぐ。check の見出しは変えない。

- [ ] **Step 2: 落ちることを確かめる**

Run:

```bash
./test-build.sh --launcher-only 2>&1 | grep -E '\[FAIL\]|結果:'
grep -c 'ERROR: GitHub meta' "$(ls -t .claude/test-results/*.log | head -1)"
```

Expected: `build と run の両方に override が渡る [FAIL]` と `build と run に共有・スキル・plugin・IPv6 の override が共存する [FAIL]` の 2 件だけが FAIL で、2 つ目のコマンドは `0`。このとき 2 件は、meta の取得には成功し（本物の通信）、足した記録の検査で落ちている（スタブが無いので記録ができない）。2 つ目のコマンドが `0` でなければ、通信の失敗で rc の検査が先に落ちていて、足した検査は評価されていない。その場合は、この Step の結果は RED の確認として数えず、そのことを PR の本文に書く（記録の検査の働きは、Step 4 の GREEN と Step 5 で確かめる）。2 件以外の FAIL があれば、止まって原因を調べる。

**REQUIRED SUB-SKILL:** Use superpowers:systematic-debugging（2 件以外の FAIL が出たとき）

- [ ] **Step 3: スタブを `launcher_sandbox_init` に移す**

`launcher_sandbox_init` の中の `chmod +x "$bin/podman"`（646 行。1003 行の同じ文は別のテストの podman の差し替えなので対象外）の直後に、Interfaces の動きをする `$bin/curl` を置く。既存のスタブ（1695〜1706 行）と同じ `#!/bin/sh` の `while` ループを使い、先頭で `printf '%s\n' "$*" >> "<root>/curl-calls"` する。`$root` は作成時に展開する（podman のスタブと同じく、引用符なしのヒアドキュメントにする）。このとき、スタブの実行時に評価する `$#`・`$1`・`$2`・`$*` の 4 つは `\$#`・`\$1`・`\$2`・`\$*` とエスケープする。作成時に展開するのは `$root` だけ。コメントを 1 行付ける（例: 「`-b` の meta 取得（`stage_build_context`）を通信なしで通す。本物の取得に頼ると、スナップショットの無い checkout（CI）で一時的な失敗が rc 1 になる（#213）」）。1695〜1707 行と 1993〜2005 行の個別のスタブを消す。

- [ ] **Step 4: 通ることを確かめる**

Run: `./lint.sh; echo rc=$?` と `./test-build.sh --launcher-only 2>&1 | grep -E '\[FAIL\]|結果:'`
Expected: `lint.sh` は rc 0 で、WARNING は Global Constraints が許すものだけ（podman が無ければ Compose 検証は `not run`）。`--launcher-only` は FAIL 0 で、PASS は Step 0 で控えた T と同じ（check は足していない）。

- [ ] **Step 5: 通信が失敗しても通ることを確かめる**

```bash
S=$(mktemp -d)
printf '#!/bin/sh\necho "fake curl: network down" >&2\nexit 7\n' > "$S/curl"; chmod +x "$S/curl"
PATH="$S:$PATH" ./test-build.sh --launcher-only 2>&1 | grep -E '\[FAIL\]|結果:'
rm -rf "$S"
find .build-context -name 'github-meta*' 2>/dev/null | wc -l
```

Expected: FAIL は `通信待ちの上限・再試行・スナップショット保護` の 1 件だけ（本物の `curl` を要するテストなので、偽の `curl` では落ちる。直す前の同じ実験では、これに加えて 1341 行と 2121 行の 2 件が落ちた）。`find` の行は `0`（テストの後片付けがスナップショットを残していない。空の `.build-context/` ディレクトリは残ってよい。`launcher_sandbox_cleanup` は中のサブディレクトリだけを消すため）。

- [ ] **Step 6: commit する**

```bash
git add test-build.sh
git commit -m "test: launcher テストの GitHub meta 取得をサンドボックスのスタブにする（#213）"
```

本文に、原因（スタブの無い 2 件が本物の meta を取得し、スナップショットの無い checkout では一時的な失敗で rc 1 になる）と、Step 5 の実験の結果を書く。末尾に、システムが指定する Co-Authored-By と Claude-Session の行を付ける。

### Task 2: PR を作る

- [ ] **Step 1: 検証の結果をそろえる**

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

Task 1 の Step 2・4・5 の出力（FAIL の行、`結果:` の行、Step 2 の `ERROR: GitHub meta` の件数）を、PR の本文に貼れる形で手元に残す。

- [ ] **Step 2: push の確認を持ち主に求める**

`.claude/AGENTS.md` の規則により、push の前に持ち主へ確認する。ブランチ名 `fix/launcher-meta-stub-213` と commit を示す。

- [ ] **Step 3: push して PR を作る**

**REQUIRED SUB-SKILL:** Use superpowers:finishing-a-development-branch

finishing-a-development-branch の「push して PR を作る」を選ぶ（番号ではなく名前で選ぶ）。`gh` はコンテナ内では PAT を明示して渡す（README.md「PAT を gh CLI に明示的に渡す」の形。`GITHUB_MAIN_PAT` をサブシェルの中で読む）。PR の本文に書くこと:
- 原因と直し方（この計画の「背景と確認済みの原因」の要約）。#213 の本文の「`$out` は CI のログに出ない」は誤りで、`ci.yml` は失敗時に `.claude/test-results/*.log` を出すことを添える。
- 検証: `./lint.sh` rc 0（出た WARNING をそのまま書く）、`--launcher-only` FAIL 0、Step 2 の RED（記録の検査で落ちたか、通信の失敗で評価されなかったか）、Step 5 の実験の結果。
- not run: Compose 検証（podman が無い環境で実行した場合。CI の `lint とビルド不要のテスト` で確かめる）。run 39019871090 attempt 1 の CI ログの確認（コンテナの firewall でログの置き場に届かない）。実ビルド（`./test-build.sh` の全体）（実 podman が要り、この変更は launcher のサンドボックスだけに効くため）。
- 区分: 通常。PR 後の二重レビュー（Claude と Codex）は、作成に関わっていない対話セッションが担う。
- `Closes #213`。末尾に署名 `— <実効モデル名> (c3c)` と、システムが指定する PR の帰属の行。

- [ ] **Step 4: 必須 CI を確かめる**

Run: `gh pr checks <番号> -R jj1xgo/c3c --watch`（PAT を明示して渡す）
Expected: `lint とビルド不要のテスト`・`Analyze (actions)`・`Analyze (python)`・`CodeQL` がすべて pass。

- [ ] **Step 5: 実績を記録し、handover を残す**

保守者の非公開の実績の台帳の「本運用の記録」節に、この作業の行を事実だけで足す（実装者のモデル、手戻りの有無、計画レビューの記録節にある各レビュアーの所要、利用枠の残量は取れなければ「未取得」）。続けて、PR 後の二重レビューとマージを別の対話セッションに渡すため、保守者の handover の手順で handover を書く（PR 番号、head、区分: 通常、事前レビューは無いので差分を全文精読すること、`.c3c/allowed-domains.txt` の未コミットの行を守ること、worktree `/workspace/.worktrees/launcher-meta-stub-213` の片付け）。

## 計画レビューの記録

- Self-Review: Task 1 Step 3 の podman の `chmod` の行が 2 か所ある（646・1003 行）ことを明記、Step 4 の PASS の比べ方の曖昧さを修正
- Claude（claude-opus-5-5、所要 173 秒）: 修正後に渡せる。生の出力はハーネスの一時出力（公開しない）
  - I1 Step 5 の `ls .build-context` の Expected が成り立たない（cleanup は親ディレクトリを残す）→ 採用（`find … -name 'github-meta*' | wc -l` が `0` に変更、Review Focus 5 も揃えた）
  - I2 コンテナ内では `lint.sh` が podman 不在の WARNING を出すので「警告ゼロ」を満たせない → 採用（Global Constraints・Step 4・PR 本文に、許す WARNING と Compose 検証の `not run` を書き分けた。podman 不在はコンテナ内で確認済み）
  - M1 Step 0 で FAIL が出たときの PASS の比べ方 → 採用（PASS と FAIL の和を T として控える）
  - M2 記録の検査を meta の URL に限る → 採用（`grep -qF 'https://api.github.com/meta'`）
  - M3 2121 行の式に足す位置 → 採用（`|| exit 1` の前と明記）
  - M4 ヒアドキュメントでエスケープする変数の列挙 → 採用
  - M5 実績の台帳への記録の Step が無い → 採用（Task 2 Step 5）
- Codex（gpt-6-astra、所要 68 秒）: 修正後に渡せる。生の出力はハーネスの一時出力（公開しない）（起動前にコンテナで canary 合格、rc 0、所要 15 秒、持ち主の依頼で実行）
  - I1 Step 5 の後片付けの Expected が実装と合わない → 採用（Claude I1 と同じ修正）
  - M1 初回に FAIL が出たときの PASS の比べ方 → 採用（Claude M1 と同じ修正）
  - M2 RED の理由を確かめていない（通信の失敗では記録の検査まで届かない）→ 採用（Step 2 に `ERROR: GitHub meta` の件数の確認と、0 でないときの扱いを追加）
  - M3 Compose 検証ができない環境の扱い → 採用。深刻度は Claude I2 と割れたので重い方の Important を暫定で採る。`LINT_SKIP_COMPOSE=1` は不採用（podman が無ければ `lint.sh` が自分で飛ばす。`lint.sh:303`、README.md 763 行）
  - M4 スキル指定を該当 Step の先頭に、handover は SKILL.md のパスで → 採用
- 確認限定巡 1: Codex（I1、所要 21 秒）→ 直った、実装に渡せる。生の出力はハーネスの一時出力（公開しない）
- 確認限定巡 1: Claude（I1・I2、claude-opus-5-5、`--resume`、所要 11 秒）→ 両方直った、実装に渡せる。生の出力はハーネスの一時出力（公開しない）

区分: 通常（変更は `test-build.sh` のテストのサンドボックスだけで、`c3c` 本体の境界の処理〈meta の取得、スナップショットへの切り替え、`ERROR` の条件〉にも `docs/development-invariants.md` の対象ファイルにも触れない。規則・権限・秘密の扱いも変えない）
推奨実装: Sonnet（判定順の 1〜5 に当たらない。コンテナでも CI でも動き、設計判断は残っておらず、Opus を推す条件〈`~/.claude` の挙動、hook、秘密、不可逆・対外操作、セキュリティ境界〉にも当たらない。push と PR 作成は持ち主の確認を経る。c3c の Claude Code 面のプロジェクト既定も Sonnet）
