# 旧入口削除（段階C）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 配布する入口を通常ファイルの `c3c` に一本化し、旧 `claude-container` 実行ファイルと旧入口分岐を削除する。

**Architecture:** 既存 c3c の parser・選択記憶・dispatch を正とする。ファイル移動と旧分岐除去に限定し、コンテナ境界・認証・設定・ビルド入力は変更しない。

**Tech Stack:** Bash、Python unittest、Podman/Compose。

**Spec:** [廃止計画](2026-09-22-retire-claude-container-command.md) §1・4・5。

## 開始条件と実行方法

- 基点は `v11.1.0`、commit `cf0389c5424315b8e4dc7ab5ac8827a6cf0dfda1`。旧計画冒頭の PR draft 状態は過去の記録。段階Aは PR #141 と v11.1.0 で公開済み。
- 段階Bは管理対象3プロジェクトの両 CLI 起動・終了・再開、PATH 入口の移行を完了。通常/Codex 診断とも FAIL 0。詳細・復元手順は非公開運用記録に保存し、公開計画へ個人のパスを転記しない。
- 変更前 `TMPDIR=/tmp ./test-build.sh --launcher-only`: PASS=253 / FAIL=0。新しい専用 worktree は基点から作成し、製品変更なし。
- Fable を読み取り専用で呼んだが利用枠上限で失敗したため、グローバル運用に従い Codex が具体化し Opus が計画レビューする。
- 実行方式は `superpowers:executing-plans`（同一実装者が順に実行）。実装開始前に計画レビューの Important 以上を解消し、反映後は確認限定巡を1回行う。
- commit・push・PR作成・merge・タグ作成は本計画だけでは許可しない。作業差分と検証結果を提示してから既存の承認範囲を照合する。

## Global Constraints

- 旧 `.claude-container.d/` の互換読込、`CLAUDE_CONTAINER_*`、state パス、Compose の service・image・label、認証・MCP 承認先を維持する。
- `c3c` の引数・終了コード・記憶・初回選択は維持する。旧名の外部 symlink でも旧 parser を復活させない。
- `resolve_launcher_path()`、アセット正本、ガード、環境読込より前の freeze、終了コード保存の順序を変えない。
- Dockerfile、entrypoint、compose、ハッシュ対象の変更は予定しない。必要になった場合はその理由と追加のビルド検証を提示し、単なる名前置換で変更しない。
- `docs/development-invariants.md` の launcher・check・選択記憶を編集前に読む。歴史記録、製品名、Issue URL、内部識別子は一括置換しない。
- 各編集ターン内に `./lint.sh` を実行。Podman 制約で失敗した場合はホストで補い、スキップを成功扱いにしない。

## Review Focus

1. 旧 basename の外部 symlink: 新 parser と選択記憶を使い、別ディレクトリからの多段相対リンクでもアセット基点を解決する（Task 1）。
2. 非TTY・記憶なし: test fixture の旧 Claude 固定呼出しを明示指定へ移し、製品側の選択拒否を緩めない（Task 2）。
3. `--check`/`--clean`: 初回選択や記憶読書きが増えず、対象0件・複数件・FAIL併存・欠落清掃の契約を維持する（Task 1/2）。
4. `readonly` と dispatch: env 読込前の agent 確定と記憶キー保護、異常終了時の記憶不変を維持する（Task 1/3）。
5. 本体移動後の build context: コピー元・関数抽出元を全て更新し、hash・既存イメージ・MCP承認を再利用する（Task 2/3）。

### Task 1: 新入口の配布形態と旧名 symlink の契約

**Files:** `tests/test_c3c_launch.py`、`tests/test_c3c_config.py`（共有fixture利用側）、`c3c`、`claude-container`（削除）。

**Interfaces:** 既存 `LaunchCase.run_entry()`・`run_c3c()`・fake Podmanを消費。通常ファイル `c3c` と basename 非依存の新契約を後続へ提供。

- [ ] `test_c3c_is_a_symlink_to_the_launcher` を下記の配布契約へ変更し、変更前に失敗を確認する。

```python
def test_c3c_is_the_only_executable_launcher(self):
    self.assertTrue((REPO / 'c3c').is_file())
    self.assertFalse((REPO / 'c3c').is_symlink())
    self.assertTrue(os.access(REPO / 'c3c', os.X_OK))
    self.assertFalse(os.path.lexists(REPO / 'claude-container'))
```

Run: `python3 tests/test_c3c_launch.py LaunchCase.test_c3c_is_the_only_executable_launcher -v`

Expected: `is_symlink()` の assertion で FAIL。import/setup エラーは RED の証拠にしない。

- [ ] `test_legacy_name_via_relative_symlink_resolves_the_same_run_dir` と `test_legacy_entry_keeps_lenient_parsing` を旧名の外部リンク契約へ更新。リンク自体は fixture の外部 bin に作り、先は runner/c3c。新 parser の未知オプション/余分なdirectory/重複agentは rc2、保存済み Codex を無指定で選ぶこと、明示Claudeで上書きできることを `run_entry()` と既存 preference helpers で検証する。配布ツリーに旧名を再作成しない。
- [ ] 新旧 basename の help は同じ c3c usage にする。旧入口の警告専用 assertions を撤去し、check の無書込・対象0件・FAILを隠さない検査は c3c 契約として残す。
- [ ] symlink `c3c` を外して `claude-container` を `c3c` へ移す（通常ファイル・実行属性を保持）。`c3c` symlink を開いて上書きする方法は使わない。
- [ ] `INVOKED_NAME`/`C3C_INTERFACE` 定義、旧 usage、旧 parser、`guard_legacy_entry()` と全呼出しを削除。新 parser 本体は保持する。c3c usage の廃止予定記述（基点89/110行）も削除済みの案内へ更新し、旧入口前提の冒頭/parser/dispatchコメントを同時に追従する。
- [ ] `finalize_agent()` の新入口エラーだけを残し、parser直後の旧入口向け早期確定を削除。dispatch の check/clean 各経路では一度だけ確定、通常起動では `freeze_agent_preference_key` → `select_c3c_agent` → `finalize_agent` を無条件に行う。
- [ ] check INFO（基点2393行）は「旧入口は削除済み。外部スクリプト・alias・PATHの呼出しは c3c claude / c3c codex へ移行してください」とし、READMEとtest_c3c_launchのassertionを揃える。`C3C_INTERFACE=0` のenv注入は削除済み変数に対する空振りになるため除去し、C3C_PREF_KEY/CC_STATE_DIRの保護検査は残す。新parserでは到達不能になるdispatchの引数なしusage/exit1（基点2522–2525行）は削除する。
- [ ] 末尾の記憶更新は `run_rc == 0` だけを条件にし、`run_main_compose` の失敗コード保存を維持する。
- [ ] fixture の `self.launcher` を runner/c3c に更新。`run_legacy()` は削除せず、fixture外部binの旧名symlinkから新c3cを実行するhelperへ再定義する。`test_c3c_config.py` の両basenameループを維持し、通常起動のClaude固定ケースだけ明示指定を足す（基点172–173行を含む）。旧固定動作を期待するassertionは除去するが、旧設定 directory は残す。絶対/相対/多段リンク、PATH、`bash ./c3c`、danglingリンクの検査を維持。

Run: `python3 -m unittest discover -s tests -p 'test_c3c_*.py'` と `./lint.sh`。共有fixtureをimportする設定suiteも成功して初めてTask 1を完了とする。

Expected: 新契約・既存新入口テスト成功。lint が旧実行パス依存だけで失敗する場合は該当箇所を Task 2 の同一変更として直し、成功前に Task 1 完了としない。

### Task 2: 全検証入口と現行文書の移行

**Files:** `test-build.sh`、`lint.sh`（参照確認のみ、git ls-filesとshebangで列挙するため変更不要）、`tests/test-lint-compose-checks.sh`、`tests/test_c3c_config.py`、`tests/test_codex_launch.py`、`tests/test_agent_preference.py`、`tests/test_project_images.py`、`tests/test_network_timeouts.py`、`tests/test_codex_entrypoint.py`、`README.md`、`AGENTS.md`、`docs/development-invariants.md`、`docs/firewall-refresh.md`、`SECURITY-CLAIMS.md`、CI内の該当実行パス。

**Interfaces:** Task 1 の通常ファイル c3c を消費。全既存境界テストを新入口で実行できる状態を提供。

- [ ] `git grep -n claude-container -- test-build.sh lint.sh tests .github README.md AGENTS.md 'docs/*.md' SECURITY-CLAIMS.md` を取得し、実行/コピー/抽出元と維持すべき識別子に分類する。docs/superpowersの歴史記録は置換対象外。製品名のWARNING（基点856行とtest_codex_launch.py:279）、旧設定名、stateパス、Issue番号は維持する。
- [ ] `TMPDIR=/tmp ./test-build.sh --launcher-only` で旧コピー元/実行パスによる失敗を確認する。Task 1 の fixture 変更に由来する別の失敗を混同しない。
- [ ] `test-build.sh` の通常起動 helpers と通常起動直接呼出しは `c3c claude` に移す。`--check`/`--clean` に不要な `claude` を挿入しない（clean はagent指定を拒否）。Codex明示の既存呼出しは `c3c --agent codex` を維持できる。
- [ ] Claude明示追加の基点箇所: `tests/test_c3c_config.py:172-173`、`tests/test_codex_launch.py:253` の空引数ケース・`:270`・`:363`、`tests/test_project_images.py:449`、`test-build.sh:589`・`:796`・`:821`・`:887` の `.` ケース・`:1437`・`:1543`・`:2038`。行番号は基点の目印で実コードも照合する。`prompt_c3c_agent`/`select_c3c_agent` は緩めない。CC_AGENT注入を拒む検査は明示ClaudeのCC_AGENT=claude assertionを維持し、記憶側の保護試験と両方を残す。
- [ ] 関数抽出 `sed`/Python `read_text` の元を c3c に変更。runnerのコピー一覧を c3c に変更し、旧ファイル不在でも config-ro fixture が本物のlauncherを実行するようにする。`run_config_ro_launcher_tests` のコピー一覧（基点1328行）には `agent-preference.py` も加え、helper欠落の退化経路で試験しない。
- [ ] Python旧suiteの起動対象を c3c へ移す。Claude固定が目的の通常起動には明示指定、記憶が目的のsuiteには指定を加えない。parser旧仕様のテストだけを新契約へ変更し、ガード・認証・MCP・ネットワークの assertions は残す。
- [ ] READMEの導入/アーキテクチャ/廃止案内を更新。旧入口は削除済み、移行は `c3c claude` / `c3c codex` と記す。設定互換は維持。AGENTSの「c3cはsymlink」と不変条件の旧入口例外を削除し、新しい本体名へ追従。
- [ ] 既存廃止計画の先頭状態を段階A/B完了・C実装中へ更新する。過去の測定行は上書きしない。

Run: `./lint.sh`、`TMPDIR=/tmp ./test-build.sh --launcher-only`、`git diff --check`

Expected: 全成功・警告なし。削除する旧入口専用テストの名前と代替検査を記録し、単に件数減少で全成功としない。追加の閉包確認として `git grep -n -e 'SCRIPT_DIR}/claude-container' -e 'runner / "claude-container"' -e "runner / 'claude-container'" -e 'bash -n claude-container' -- test-build.sh lint.sh tests .github` は実行/コピー/抽出参照0件（rc1）を期待する。旧ファイル不在をassertするテストのREPO参照は残してよい。全体モード専用の基点1695行（bash -n）、1807行（対応版抽出）、2038行（env非混入）の更新を個別確認する。

### Task 3: ハッシュ不変と実 Podman 受入

**Files:** Task 1/2 の不足を直す場合だけ変更。結果は計画末尾と非公開実測記録に追記。

**Interfaces:** 新入口と全fixtureを消費。削除版の公開判断に使う実測記録を提供。

- [ ] `ASSET_HASH_TARGETS` の21項目と実在ファイル内容が基点と一致することを比較。launcherは対象に含まれない。fixtureで `compute_asset_hash()` の基点/変更後の出力を同じプロジェクト設定に対して比較し、一致を確認する。
- [ ] fake Podman の `image_exists=True` で本起動し、build呼出しなし・既存承認再利用を確認する。ホストでも既存イメージラベルと承認記録を控え、再起動後に不必要なbuild/再承認がないことを確認する。
- [ ] `TMPDIR=/tmp ./test-build.sh --config-ro-only` を実 Podman ホストで実行。さらに全体 `TMPDIR=/tmp ./test-build.sh` を実行し、全体モード専用の構文・対応版抽出・env非混入試験も通す。実行不能なら当該3項目を名指しで not run とし、未検証のまま公開しない。

Expected: rc0。:ro mount と実launcher準備処理の全検査が成功。実行不能は not run とし公開条件未達とする。

- [ ] 隔離worktreeの新本体から管理対象を明示して両CLIを起動。CLI明示・前回選択・正常終了・異常終了・専用の名前付き会話再開を確認。既存の利用者会話を使わず、認証設定の変更やMCP再承認を自動で行わない。
- [ ] 異常終了試験は今回作成したコンテナIDのみを対象にする。Claude TERM/Codex KILL のランチャーrcと選択記録不変を確認し、信号送信用podman自身のrcと混同しない。
- [ ] 新本体を指す試験用PATH symlinkと多段相対symlinkで `--check` と起動を確認。実利用PATHの切替は実測完了後の別操作にする。

Expected: 両CLIの通常終了rc0、異常終了時は非0かつ記憶不変、会話復元成功、check FAIL0。既存の警告は内容を記録し今回の回帰と区別する。

### Task 4: レビューと引き渡し

**Files:** 本計画の結果欄、PR準備資料。

**Interfaces:** 全検証と非公開移行記録を消費。レビュー可能な差分と公開条件一覧を提供。

- [ ] 旧入口不存在、実行属性、残存旧名参照の分類、変更範囲外の差分不在を確認。
- [ ] 実装者に適用される独立レビューを実施し、Critical/Importantを修正。Codex実装へ担当変更した場合はPR前に `claude-review` を1回実施する。
- [ ] commit・push・PRの承認範囲を確認。PRは段階Aと別、本文は削除後の利用者契約を説明する。段階A/B記録と必須CI成功を公開条件にする。
- [ ] コミット完了後、旧コマンド削除によるMAJORとして `v12.0.0` を提案する。タグはユーザー承認後のみ作成。マージ権限はグローバル指示に従う。

## 実装担当

実装: Opus — launcherのagent確定・env読込前freeze・終了コードと記憶更新をまたぐ旧分岐除去であり、境界条件を含むテスト移行にも判断が残るため。Claudeの同一セッションで計画を読み、Plan Modeで確認後、`/model` ピッカーでOpusを選び `s`（セッション限定）としてから executing-plans で実装する。

## 計画レビュー対応

- Opus 5 の初回判定: Critical 0 / Important 3 / Minor 10。Important 1は共有fixtureの依存と同時GREEN、2は明示Claude追加箇所、3は全体モード専用参照の検証不足。上記へ反映。
- Minor 1–7・9–10も手順に反映。Minor 8のhash出力比較削減は採らず、アセット内容不変に加えてresolver/compute関数の結果も比較する。元checkoutが同じ基点ツリーで残るため、比較のための追加worktreeは不要。実行経路の退行も拾う目的。
- レビュアーが実行しなかった範囲（CI、実Podman、長いREADME行等）はTask 2/3/4の実装者の確認対象。初回静的レビューを実測の代用にしない。
- 確認限定巡: Opus 5 が Important 3件すべての解消と実装開始可を確認。実装担当Opusを維持。製品実装は未着手。

## 実測結果（段階C 実装、2026-09-22、Opus 5）

- Task 1: `test_c3c_is_the_only_executable_launcher` の RED（`is_symlink()` で FAIL）を確認後、`git rm c3c && git mv claude-container c3c`（mode 100755 の通常ファイル）。`INVOKED_NAME`/`C3C_INTERFACE`、`guard_legacy_entry()` と呼出 3 箇所、旧 usage、旧 parser、`finalize_agent()` の旧文言分岐と parser 直後の早期確定、dispatch のガード 4 箇所、到達不能の引数なし usage/exit 1、記憶更新条件の入口判定を削除。`python3 -m unittest discover -s tests -p 'test_c3c_*.py'` 64 件 OK、`./lint.sh` rc0。
- Task 1 で削除・改名したテストと代替: `test_legacy_run_warns_and_keeps_claude_and_saved_preference` は削除（旧固定動作は仕様から消えた。代替は `test_legacy_name_via_relative_symlink_uses_the_c3c_contract`: 同じ RUN DIR、保存済み Codex を無指定で採用、明示 claude で上書き・保存）。`test_legacy_entry_keeps_lenient_parsing` → `test_legacy_name_uses_the_strict_c3c_parser`（未知オプション・複数 dir・重複 agent・非 TTY 無記憶 = rc2、引数なしは cwd）。`LegacyRetirementTests` → `CheckMigrationInfoTests`（対象0件・複数件・FAIL 併存〈実測 PASS0 WARN1 FAIL1〉・欠落清掃で INFO 1 行と無書込、旧 WARN 不在）。`test_check_clean_and_legacy_never_touch_memory` → `test_check_and_clean_never_touch_memory`（旧名 symlink の通常起動ケースは記憶を使うため除外、`--check` ケースは旧名経由も維持）。旧名の help は c3c と同一出力。`test_project_env_cannot_move_or_disable_memory` の env 注入から `C3C_INTERFACE=0` を除去（`CC_STATE_DIR`/`C3C_PREF_KEY` の保護検査は維持）。
- Task 2: `--launcher-only` は変更前 rc1 PASS74 FAIL162（旧実行パス）→ 移行後 rc0 PASS253 FAIL0。test-build.sh は実行/コピー/抽出参照を c3c へ、通常起動 11 箇所に `claude` を明示、runner コピー一覧に `agent-preference.py` を追加。Python 旧 suite は起動対象を c3c に移し、Claude 固定の通常起動（`test_codex_launch.py` の `[]`→`['claude']`・env 注入拒否・label 無視、`test_project_images.py` の live 起動）にだけ明示指定を追加。閉包 grep（`SCRIPT_DIR}/claude-container`・`runner / 'claude-container'`・`bash -n claude-container`）0 件、`git diff --check` rc0、`./lint.sh` rc0。維持した識別子: label `claude-container.*`、`.claude-container.d`、state/approval/mount パス、`CLAUDE_CONTAINER_*`、Issue 番号、製品名 WARNING、歴史記録。
- Task 3: ASSET_HASH_TARGETS 21 項目・各ファイル内容が基点と一致、`compute_asset_hash()`（resolver 込み）の出力が基点 launcher と新 launcher で同一。実 Podman `--config-ro-only` rc0 PASS25 FAIL0、全体 `./test-build.sh` rc0 PASS384 FAIL0（`bash -n c3c`・対応版抽出・env 非混入の 3 項目とも PASS）。管理対象 3 プロジェクト × 両 CLI: 新本体（worktree）からの明示起動→専用の名前付き会話作成→rc0→再起動→`/resume` で識別子復元→rc0（全 6 組）。build なし・ドリフト WARN なし・MCP 承認プロンプトなし。無指定起動は `前回の選択: codex` を表示して rc0。異常終了（自コンテナのみ）: Claude TERM → rc143、Codex KILL → rc137、記憶不変・コンテナ消滅。PATH 上の多段相対 symlink 経由の `--check`（通常/Codex）は rc0 PASS1 WARN2 FAIL0（WARN は既存の旧名設定 directory・requirements.txt 欠落）、同 symlink 経由の Claude 起動も RUN DIR が新本体。前後で 3 イメージの ID・label、MCP 承認記録、選択記憶の内容は不変。
- not run: 実利用 PATH の削除版への切替（公開後の別操作）。CI は PR 作成後に確認。
