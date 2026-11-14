# Copilot の起動口に Fusion の段階を渡す口を足す 実装計画（#265）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目的:** c3c の Copilot の起動口（`copilot-launcher.sh`）が、第 1 引数の `--c3c-fusion-tier <standard|high|max>` を受け取って取り除き、起動のたびに作り直す `settings.json` の `fusionTier` にその値を書く。指定しない起動の振る舞いは変えず、決まった形以外は Copilot を起動せずに ERROR で止める。

**構成:** 引数の解釈は起動口の最初の段（`fail()` の定義の直後、中継と実体の検査の前）に置き、`shift 2` で取り除く。値は `settings.json` を作り直す既存の `python3 -I` に 7 番目の引数（指定なしは空文字）で渡し、書いた後の検査に、作り直した内容との全体の一致を足す。sandbox の設定の検査は変えない。

**使う技術:** bash、Python 3（標準ライブラリ、`unittest`）、shellcheck（`./lint.sh`）。

**仕様:** `docs/superpowers/specs/2026-11-14-copilot-fusion-tier-design.md`（commit 5e317ef。計画レビューの初回は amend の前の 16f4c69 で読んだ。違いは設計書の 1 語だけ）

**経緯:** Copilot CLI 1.0.109 は Fusion の段階を設定ファイルの `fusionTier` でしか受け取らない。起動口は `COPILOT_HOME` を固定し `settings.json` を雛形から毎回作り直すので、コンテナの中から段階を指定できず、保守者の並走の道具はコンテナでの Fusion の起動を止めている（Issue #265）。

作業ブランチは `feat-copilot-fusion-tier`（作成済み、`main` の `a1798a6` から。spec の commit 5e317ef を含む）。計画の承認の直後に、計画者がこの計画を `docs/superpowers/plans/2026-11-14-copilot-fusion-tier.md` に写して commit する（公開の置き場。「計画レビューの記録」の一時パスと session ID は「（非公開の場所に保存）」に置き換え、commit の前に `grep -nE "$(id -un)|/tmp/|session" docs/superpowers/plans/2026-11-14-copilot-fusion-tier.md` の出力を目で見て、ホストのパス・ユーザー名・session ID が残っていないことを確かめる。`/home/node` は c3c の公開の配置なので残ってよい）。実装者はその commit の上から始める。

**実行の場所:** タスク 1 と、タスク 2 の手順 1〜5 はホストで行う（手順 2 は実 podman が要る）。タスク 2 の手順 6（`-b` での作り直し）は保守者がホストの端末で行う。手順 7・8（作り直した opt-in のコンテナでの実機の確かめ。クレジットを使う）は、保守者がそのコンテナの入力欄で `!` で打つ。

## 全体の制約

**REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（コードを変える計画。タスク 1 の前に 1 回読み込む）

- 口の形は `--c3c-fusion-tier <値>` の 2 語だけ。値は `standard`・`high`・`max` のどれかと完全一致（大文字・前後の空白・空文字は不可）。解釈するのは第 1 引数だけ（spec「設計者の判断」）。
- 止める形（どれも `ERROR:` を stderr に出して rc 1、Copilot を起動せず、`COPILOT_HOME` も lock も `settings.json` も作らない）: 第 1 引数が `--c3c-fusion-tier` で値が無い／値が 3 つ以外／取り除いた直後の第 1 引数がもう一度 `--c3c-fusion-tier` か `--c3c-fusion-tier=` で始まる、または第 1 引数が `--c3c-fusion-tier=` で始まる。
- 第 2 引数以降の `--c3c-fusion-tier` は、取り除かず、そのまま Copilot に渡す。ただし、段階を受け取って取り除いた直後の第 1 引数（元の第 3 引数）が `--c3c-fusion-tier` か `--c3c-fusion-tier=` で始まるときは、上の止める形として止める（二重の指定）。`--c3c-fusion-tier high high` のように直後が値の形でも、それは二重の指定ではなく、`high` をそのまま Copilot に渡す。
- 指定しない起動では、`settings.json` の中身を今と同じにする（雛形の写し＋`readonlyPaths`。雛形に `fusionTier` があってもそのまま）。指定した起動では、雛形の `fusionTier` の有無によらず指定の値で上書きする。
- sandbox の設定の検査（弱めた設定、未知のキー、真偽値でない値は不合格）、雛形 `copilot-settings.json`、`VERIFIED_COPILOT_VERSION`、トークンの読み方、環境の allowlist は変えない。
- 引数の値をトークンや環境に混ぜない。ERROR の文に受け取った値を出さない（制御文字を端末に出さないため）。
- ERROR の文は `fail` に渡す本文を `第 1 引数の --c3c-fusion-tier には standard・high・max のどれか 1 つを、別の引数で渡してください（Copilot を起動しません）。` に固定する（`fail()` が先頭に `ERROR: ` を付ける。本文に `ERROR: ` を含めない）。試験は `--c3c-fusion-tier` を含むことで照合する。
- 挙動を変える commit には README と不変条件の文の更新を同じ commit に含める（root `AGENTS.md`「開発の進め方」）。
- 編集したら、そのターン内で `./lint.sh` を rc 0・警告ゼロで通す。日本語で書く。保守者個人のもの（ホストのパス、非公開のリポジトリの名前、並走の台帳）をコード・試験・README に書かない。

## レビューで見てほしい点

1. プロンプトの値などに `--c3c-fusion-tier` がある起動（第 2 引数以降）で、起動口が取り除いたり止めたりしないこと（タスク 1 `test_fusion_tier_later_args_pass_through`）。
2. 前の起動で `max` を書いた後、指定なしの起動で `fusionTier` が残らないこと（タスク 1 `test_fusion_tier_does_not_persist`）。
3. 不正な形で、Copilot の起動だけでなく `~/.copilot` の作成や lock の取得より前に止まり、受け取った値を stderr に出さないこと（タスク 1 `test_fusion_tier_refused`）。
4. 雛形に `fusionTier` があるとき、指定なしでは変わらず、指定ありでは上書きされること（タスク 1 `test_fusion_tier_with_template_value`）。
5. 実機で、書いた `fusionTier` を Copilot が読み、その回の `session.fusion_resolved` に出ること（タスク 2 の手順 7。試験の偽の Copilot では確かめられない）。

---

### タスク 1: 起動口が段階の引数を受け取り、`settings.json` に書く（README と不変条件の文を含む）

**Files:**
- Modify: `copilot-launcher.sh`（冒頭の説明の段の一覧、`unset -v` の行、`fail()` の直後、`python3 -I` の設定の作り直しと検査、最後の `unset` の行）
- Modify: `README.md`（「Copilot CLI を使う」節の「起動口が止める条件」の一覧と「sandbox の設定」の段落の後、「変更後の確認」の Copilot の段落）
- Modify: `docs/development-invariants.md`（`copilot-launcher.sh` の項の「順序」の行と、`settings.json` の作り直しの行）
- Test: `tests/test_copilot_launcher.py`

**Interfaces:**
- Produces: 起動口の CLI `copilot [--c3c-fusion-tier standard|high|max] [Copilot の引数…]`。タスク 2 の実機の確かめはこの形で起動する。

- [ ] **手順 1: 失敗する試験を書く**（`tests/test_copilot_launcher.py`。`TIERS` はモジュールの定数として `VERIFIED` の近くに置き、ほかは `# --- settings.json の作り直し` の節の後に `# --- Fusion の段階` の節を足してクラスのメソッドにする）

```python
TIERS = ('standard', 'high', 'max')

def test_fusion_tier_written(self):
    for tier in TIERS:
        with self.subTest(tier=tier):
            result = self.run_launcher('--c3c-fusion-tier', tier, '-p', 'a b', '--model', 'fusion')
            self.assert_ran(result)
            self.assertEqual(self.recorded_argv(), ['-p', 'a b', '--model', 'fusion'])
            expected = self.expected_settings(self.work)
            expected['fusionTier'] = tier
            self.assertEqual(json.loads(self.settings.read_text()), expected)

def test_fusion_tier_does_not_persist(self):
    self.assert_ran(self.run_launcher('--c3c-fusion-tier', 'max', '--version'))
    self.assertEqual(json.loads(self.settings.read_text())['fusionTier'], 'max')
    os.unlink(str(self.record) + '.argv')
    self.assert_ran(self.run_launcher('--version'))
    self.assertEqual(json.loads(self.settings.read_text()), self.expected_settings(self.work))

def test_fusion_tier_refused(self):
    cases = [
        ['--c3c-fusion-tier'],
        ['--c3c-fusion-tier', ''],
        ['--c3c-fusion-tier', 'Max'],
        ['--c3c-fusion-tier', 'max '],
        ['--c3c-fusion-tier', 'auto'],
        ['--c3c-fusion-tier', '--version'],
        ['--c3c-fusion-tier=max', '--version'],
        ['--c3c-fusion-tier=', '--version'],
        ['--c3c-fusion-tier', 'high', '--c3c-fusion-tier', 'max', '--version'],
        ['--c3c-fusion-tier', 'max', '--c3c-fusion-tier'],
        ['--c3c-fusion-tier', 'max', '--c3c-fusion-tier=high', '--version'],
    ]
    for args in cases:
        with self.subTest(args=args):
            result = self.run_launcher(*args)
            self.assert_refused(result, r'--c3c-fusion-tier')
            self.assertFalse(self.copilot_home.exists(), '~/.copilot も lock も作らない')
    for value in ('auto', 'Max'):
        with self.subTest(value=value):
            self.assertNotIn(value, self.run_launcher('--c3c-fusion-tier', value).stderr, '受け取った値を出さない')

def test_fusion_tier_later_args_pass_through(self):
    args = ['-p', 'x', '--c3c-fusion-tier', 'max', '--c3c-fusion-tier=bad']
    self.assert_ran(self.run_launcher(*args))
    self.assertEqual(self.recorded_argv(), args)
    self.assertEqual(json.loads(self.settings.read_text()), self.expected_settings(self.work))

def test_fusion_tier_with_template_value(self):
    self.write_template(lambda d: d.update(fusionTier='standard'))
    self.assert_ran(self.run_launcher('--version'))
    self.assertEqual(json.loads(self.settings.read_text())['fusionTier'], 'standard')
    os.unlink(str(self.record) + '.argv')
    self.assert_ran(self.run_launcher('--c3c-fusion-tier', 'max', '--version'))
    self.assertEqual(json.loads(self.settings.read_text())['fusionTier'], 'max')
```

あわせて既存の `test_exported_internal_names_do_not_break` の `extra` に `'fusion_tier': 'max'` を足し、最後に `self.assertNotIn('fusionTier', json.loads(self.settings.read_text()))` を足す（呼び出し元が export した同じ名前が段階として効かないこと）。既存の `test_args_passthrough` は変えない。

- [ ] **手順 2: 試験が失敗することを確かめる**

Run: `python3 -m unittest tests.test_copilot_launcher -v 2>&1 | tail -20`
Expected: `test_fusion_tier_written`・`test_fusion_tier_refused`・`test_fusion_tier_does_not_persist`・`test_fusion_tier_with_template_value` が FAIL（起動口が `--c3c-fusion-tier` を Copilot へそのまま渡し、`fusionTier` を書かないため）。`test_fusion_tier_later_args_pass_through` と、`fusion_tier` を足した `test_exported_internal_names_do_not_break` は今でも通ってよい。ほかの既存の試験は通る。

- [ ] **手順 3: 起動口を直す**（`copilot-launcher.sh`）

- 冒頭の説明の段の一覧に「0. 第 1 引数の `--c3c-fusion-tier <値>` を受け取って取り除く（値は standard・high・max だけ）」を足し、3 の説明に「段階を受け取ったときは `fusionTier` に書く」を足す。
- `unset -v` の行に `fusion_tier` を足す。
- `fail()` の定義の直後、`# 1. 中継と実体` の前に次の段を置く（`case` の文字列の比較だけで判定し、外部コマンドを使わない）:
  - `fusion_tier=""`。`$# -ge 1` で `$1` が `--c3c-fusion-tier=*` なら fail。`$1` が `--c3c-fusion-tier` なら、`$# -ge 2` で `$2` が `standard|high|max` のどれかでなければ fail、そうなら `fusion_tier=$2; shift 2`、その後 `$# -ge 1` で `$1` が `--c3c-fusion-tier` か `--c3c-fusion-tier=*` なら fail。
  - fail の本文は「全体の制約」の固定の文。
- 設定の作り直しの `python3 -I` の引数の末尾に `"$fusion_tier"` を足し、Python の側は `sys.argv[1:8]` で `fusion_tier` を受ける。
  - 受けた値が空でなく `("standard", "high", "max")` に無ければ `die`（多重の守り）。
  - `settings["sandbox"]["userPolicy"]["filesystem"]["readonlyPaths"] = [cwd]` の直後に、値が空でなければ `settings["fusionTier"] = fusion_tier`。
  - 書いた後の検査で、既存の `check(written, [cwd])` は残し、その前に `if written != settings: die(settings_path + " の中身が作り直した内容と一致しません。")` を足す（指定の有無の両方に効き、`fusionTier` の照合も兼ねる。spec「設計者の判断」の 4 つ目）。
- 最後の `unset token saved_lc_all ...` の行に `fusion_tier` を足す。

- [ ] **手順 4: 試験が通ることを確かめる**

Run: `python3 -m unittest tests.test_copilot_launcher -v 2>&1 | tail -5`
Expected: `OK`（既存の試験も含めて全部）

- [ ] **手順 5: README の「Copilot CLI を使う」節を直す**
  - 「起動口が止める条件」の一覧に 1 行: 第 1 引数の `--c3c-fusion-tier` の値が無いか `standard`・`high`・`max` 以外、`--c3c-fusion-tier=<値>` の形、2 回続けた。
  - 「sandbox の設定」の段落の後に、**Copilot Fusion の段階** の段落を足す: Fusion の段階（`fusionTier`）は Copilot CLI 1.0.109 では設定ファイルでしか渡せず、起動口が `settings.json` を毎回作り直すので、`copilot --c3c-fusion-tier max --model fusion -p …` のように第 1 引数で渡す。起動口が取り除いてその回の `settings.json` に書き、次の起動では雛形どおりに戻る。指定しなければ書かない（Copilot の既定）。第 2 引数以降の同じ文字列はそのまま Copilot に渡す（ただし段階の直後に `--c3c-fusion-tier` か `--c3c-fusion-tier=<値>` を続けた二重の指定は止める）。High と Max は契約によっては使えない（GitHub Docs「About GitHub Copilot Fusion」 https://docs.github.com/en/copilot/concepts/models/copilot-fusion へのリンク）。
- [ ] **手順 6: README の「変更後の確認」の Copilot の段落の末尾に 1 文を足す**: 起動口の段階の口を変えたときは、opt-in のイメージで `--c3c-fusion-tier` を付け、`--session-id` に新しい UUID を渡して `--model fusion` で起動し、その回の `~/.copilot/session-state/<UUID>/events.jsonl` の `session.fusion_resolved` の `data.policy` が指定した段階になることを確かめる。
- [ ] **手順 7: `docs/development-invariants.md` を直す**
  - 「順序」の行を「段階の引数の解釈 → 中継と実体の検査 → 版の比較 → …」にし、段階の引数は第 1 引数だけを `case` で解釈し、決まった形以外は何も作らずに rc 1、第 2 引数以降は変えずに渡す（段階を取り除いた直後の二重の指定は止める）、と書く。
  - `settings.json` の作り直しの行に、段階を受けたときだけ `fusionTier` を書く、書いた後に作り直した内容と全体が一致することを照合する、指定なしでは雛形の写しのまま、を足す。
- [ ] **手順 8: lint**

Run: `./lint.sh; echo rc=$?`
Expected: `rc=0`、警告なし（README のアンカーの検査を含む）

- [ ] **手順 9: commit**（挙動・試験・README・不変条件を 1 つの commit にする）

```bash
git add copilot-launcher.sh tests/test_copilot_launcher.py README.md docs/development-invariants.md
git commit -m "feat: Copilot の起動口に Fusion の段階を渡す口（--c3c-fusion-tier）を足す（#265）"
```

### タスク 2: 検証、PR 前のレビュー、実機の確かめ、PR

手順 9〜11 は、実装をサブエージェントに任せた場合もコントローラ（実装を進行するセッション）が最終レビューの後に行い、実装担当のサブエージェントに渡さない（グローバル指示の表の subagent-driven-development の行）。

- [ ] **手順 1: README「変更後の確認」の Copilot の試験**

Run: `./test-build.sh --launcher-only; echo rc=$?`
Expected: `rc=0`（`tests/test_copilot_launcher.py`・`tests/test_copilot_bwrap_shim.py`・`tests/test_copilot_config_check.py`・`tests/test_c3c_config.py` を含む）。`TMPDIR` が `/var/tmp` などの配下なら `TMPDIR=/tmp` を付ける。

- [ ] **手順 2: ビルドの確認**（ホスト。実 podman が要る）

Run: `./test-build.sh --build-only; echo rc=$?` と、全体実行 `./test-build.sh; echo rc=$?`
Expected: どちらも `rc=0`。

- [ ] **手順 3: commit が揃っていることを確かめる**

Run: `git status -s; git log --oneline main..HEAD`
Expected: 作業ツリーがきれいで、spec・計画・タスク 1 の commit がある。

- [ ] **手順 4: PR 前の二重レビュー**（区分が境界のため。グローバル指示「モデルと実装者の使い分け」）。Claude 側は `claude-review` skill（`~/.agents/skills/claude-review/SKILL.md`）、Codex 側は `codex-review` skill（`~/.agents/skills/codex-review/SKILL.md`、gpt-6.1-sol）で、どちらも作成に関わっていないセッションを起動する。Sol を起動するのはホストの Claude のセッションなので、グローバル指示の「Copilot の並走」の PR 前の段（公開の経路）にも従う。

- [ ] **手順 5: レビュー結果を受け取って直す**

**REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review

Critical・Important を直して commit し、確認限定巡で直ったことを確かめる。起動口か試験を直したら、手順 1〜3 をやり直す。

- [ ] **手順 6: 保守者がホストの端末で opt-in のコンテナを作り直す**（このリポジトリの checkout を手順 5 の後の commit にして、`.c3c/copilot-version.txt` が有効なセルフホストの c3c を、その checkout の `./c3c -b` で起動する）。起動時に `Copilot 版:` の行が出ることを見る。

- [ ] **手順 7: 段階の実機の確かめ**（保守者が opt-in のコンテナの入力欄で打つ。作業ディレクトリは `/workspace`。各回の上限 30 クレジット）

```bash
! cd /workspace && for t in standard max; do sid=$(python3 -I -c 'import uuid; print(uuid.uuid4())') && copilot --c3c-fusion-tier "$t" -p '1+1 の答えだけを書いてください' -s --model fusion --session-id "$sid" --no-ask-user --no-auto-update --max-ai-credits 30 && python3 -I -c 'import json,sys; t,p=sys.argv[1:3]; ps=[e["data"].get("policy") for e in map(json.loads, open(p)) if e.get("type")=="session.fusion_resolved"]; print(t, ps); sys.exit(0 if ps and all(x==t for x in ps) else 1)' "$t" ~/.copilot/session-state/"$sid"/events.jsonl || { echo "NG: $t"; break; }; done
```

Expected: Copilot の答えの行の後に `standard ['standard']` と `max ['max']` が出て、`NG:` の行が出ない。起動の失敗、`events.jsonl` が無い、`session.fusion_resolved` が無い、`policy` が指定と違う、のどれかなら `NG:` が出る。そのときは、出力と、その回の `events.jsonl` の `session.fusion_completed` の行（`degradedReason` を含む）を控えて、持ち主に報告して止まる（切り分けは持ち主の判断の後に別に行う）。

- [ ] **手順 8: canary**（README「変更後の確認」が起動口を変えたときに求める実機の受け入れ）

Run（保守者が opt-in のコンテナの入力欄で）: `! bash tests/copilot-canary.sh`
Expected: 全項目が合格で rc 0。使ったクレジットの行を控える。

- [ ] **手順 9: 完了の確かめ**

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion

手順 1〜8 の結果を、実行したもの・`not run` と理由に分けて控える。

- [ ] **手順 10: push と PR**

**REQUIRED SUB-SKILL:** Use superpowers:finishing-a-development-branch（push して PR を作る選択肢を名前で選ぶ）

push は保守者に確かめてから行う。PR 本文に `Closes #265`、手順 1〜8 の結果、手順 4・5 の二重レビューの判定と未対応の Minor、計画レビューの記録への参照を書き、末尾に、実効モデルを確かめた上で `— <実際のモデル名> (c3c)` の署名を付ける。手順 4 の Claude と Codex のレビューの全文を、それぞれ PR コメントに投稿する。PR 後の二重レビューとマージは、作成に関わっていない対話セッションが行う（handover で渡す）。

- [ ] **手順 11: タグの提案**。起動口に利用者から見える引数が増えるので、PR を作った時点の報告と handover に、SemVer のマイナーを上げる番号案と根拠を書いて保守者に示す（root `AGENTS.md`「バージョン管理」。タグの作成はマージと保守者の承認の後、`release-tag` skill）。

## 計画レビューの記録

- Self-Review: 推奨実装を Sonnet から Opus に直した（c3c の補足とグローバル指示の「Opus を推す条件」のセキュリティ境界）。PR の手順に receiving-code-review の指定を足した
- 版: `plan-initial.md` （非公開の場所に保存）
- Claude（claude-opus-5-5、所要 149 秒）: 修正後に渡せる。生の出力 （非公開の場所に保存）
  - I1 `test_fusion_tier_does_not_persist` が実装前から通り Red にならない → 採用（1 回目の後に `fusionTier == 'max'` を照合）
  - I2 仕様の「指定しないときは今と同じ中身」の照合が無い → 採用（書いた後に `written != settings` で全体を照合）
  - I3 PR 前の二重レビューが検証と実機の後にあり、直した後の検証が古くなる → 採用（タスク 2 の手順 4・5 に移し、直したら手順 1〜3 をやり直す。実機と verification-before-completion をその後に）
  - M1 取り除いた直後の `--c3c-fusion-tier=*` の試験 → 採用 / M2 値を stderr に出さない試験 → 採用 / M3 `fail()` が `ERROR: ` を付けるので本文から外す → 採用 / M4 export した `fusion_tier` の試験 → 採用 / M5 push・PR はコントローラが行う → 採用 / M6 PR 前の並走 → 採用（手順 4） / M7 最新のセッションを mtime で取る前提 → 採用（Codex の I2 と同じ直し方）
- Codex（gpt-6.1-sol、所要 70 秒）: 修正後に渡せる。生の出力 （非公開の場所に保存）
  - I1 挙動の変更と README の更新が別の commit で、root `AGENTS.md` の「同じコミットで」に反する → 採用（旧タスク 2 をタスク 1 に統合し、1 つの commit に）
  - I2 実機の確かめが別のセッションの記録を読みうる → 採用（`--session-id` に UUID を渡してその記録を読み、欠落も NG。1.0.109 の `--help` に `--session-id` と `-s, --silent` があることを計画者が確かめた）
  - M1 Red の Expected の食い違い → 採用（Claude の I1 と同じ） / M2 PR の署名をモデル名と (c3c) の形に → 採用
- 確認限定巡 1: Codex（I1・I2、所要 22 秒）→ 全部直った。実装に渡せる。生の出力 （非公開の場所に保存）
- 確認限定巡 1: Claude（I1〜I3、所要 9 秒）→ 全部直った。実装に渡せる。生の出力 （非公開の場所に保存）
- fusion（並走、正式外）: 修正後に渡せる（1C なし・5I・3M）。依頼した段階 max・実際の段階 max（pattern single、gpt-6-astra ×9、ruleId solo_astra_xhigh_rule_24）、起動し直しなし、131.4803 クレジット、所要 351 秒。`plan-initial.md` に対して（公開の経路、未 push、base a1798a6、commit 5e317ef）。生の出力 （非公開の場所に保存）
  - Sol と材料が違った点: 1 回目の起動は、設計書の 22 行目に非公開のリポジトリ名があり、送る前の検査で止まった（rc 2）。持ち主の判断で、その 1 語を消して spec の commit を 16f4c69 から 5e317ef に amend し、同じ経路で起動し直した。グローバル指示の AGENTS.md は渡さず、表の抜き出しを依頼文に貼った。計画のパスは `PAIRING-PLAN.md`
  - I1（README を別の commit）・I2（Red にならない試験）・I3（セッションの特定）・I4（レビューの後の検証）→ Codex の I1・I2、Claude の I1・I3 で反映済み。I2 の「`tail -20` を外す」は不採用（Red は出力で判定でき、手順 4 の Expected で rc を見ない）
  - I5 実行の場所の食い違い（手順 6 の作り直しはホスト）→ 採用（「実行の場所」と手順 6）
  - M1 失敗したときに止まるか切り分けるか → 採用（控えて報告して止まる、に統一） / M2 二重の指定の例外の書き方 → 採用（全体の制約に明記。`high high` の拒否は不採用: 直後が値の形なら二重の指定ではなく、Copilot へ渡す引数のため。`max --c3c-fusion-tier=high` は試験に有る） / M3 タグの提案の時期 → 採用（PR を作った時点の報告と handover に）
- 確認限定巡 2: Codex（fusion の I5、所要 16 秒）→ 直った。実装に渡せる。生の出力 （非公開の場所に保存）
- fusion（並走、正式外）の確認限定巡 1: I1〜I5・M1・M3 は直った、M2 は一部（README と不変条件の文を直す手順に二重の指定の例外が無い）→ 採用（タスク 1 の手順 5・7 に例外を足した）。実装に渡せる。依頼した段階 high・実際の段階 high（policy の記録は standard、degraded true、degradedReason なし。PR #267 の 2・3 巡目と同じ食い違い）、claude-opus-5.5 ×5、11.9627 クレジット、所要 29 秒、bb2bf93 に対して。生の出力 （非公開の場所に保存）

## 区分と推奨実装

- 区分: 境界（Copilot の sandbox の設定を作り直す起動口〈セキュリティ境界〉の、秘密を読む経路の手前に引数の解釈を足すため。計画・PR 前・PR 後の 3 段の二重レビュー）
- 推奨実装: Opus（判定順の 1〜5 に当たらないので c3c の Claude Code 面の既定の Claude になるが、セキュリティ境界〈sandbox の設定を作り直す起動口〉を含むので、c3c の補足とグローバル指示の「Opus を推す条件」で Opus。Sonnet でない理由: 引数の解釈の誤りが、Copilot へ渡す引数の取り違えや、検査の前の段の fail-open につながりうるため。Codex でない理由: c3c の面が Claude Code で、判定順の 4・5 に当たらない）
- 実装: Opus（持ち主指定、2026-11-14）。実行方法は実装のセッションが Plan Mode で計画を読んで決める
