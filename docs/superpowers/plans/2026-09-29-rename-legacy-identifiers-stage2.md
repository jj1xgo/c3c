# 旧製品名 claude-container の識別子の改名 第 2 段 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 旧名（`CLAUDE_CONTAINER_*` の env キー、`.claude-container.d/`、`~/.local/state/claude-container`、`claude-container.*` label、`/etc/claude-container/*`、`/home/node/.config/claude-container/secrets`）の互換読み取りを削除し、旧名は検出と移行の案内だけにする（MAJOR、v16.0.0）。

**Architecture:** 最初に launcher のゲート（既存イメージの label `io.c3c.image-layout` が `"2"` でなければ止める）を入れ、label そのものはコンテナ内のパスを変える Task 2 と同じコミットで `Dockerfile.claude` に書く（パスが旧いまま label だけ `2` のイメージを作らないため）。以降の Task はコンテナ側の非互換変更（`/etc/c3c/*`・秘密の新パス限定・新キー限定）を積むので、ゲートがあれば「旧イメージ × 新 compose」は起動前に止まる。launcher 側は旧 env キー・旧設定ディレクトリを `guard_fail` で拒否し、旧 state は読まずに案内だけを出す。`project-images.py` は旧 label を由来判定に使わず、旧 label だけのイメージを診断で示す。

**Tech Stack:** bash（`c3c`・`entrypoint.sh`・`init-firewall.sh`・`git-askpass.sh`・`lint.sh`・`test-build.sh`）、Python 3（`project-images.py`・`ipv6-firewall.py`・unittest）、Podman Compose YAML、Dockerfile。

**Spec:** `docs/superpowers/specs/2026-09-27-rename-legacy-identifiers-design.md`（「第 2 段（MAJOR）」節・「範囲外」節・「検証」節の第 2 段）。第 1 段の実装は `docs/superpowers/plans/2026-09-27-rename-legacy-identifiers-stage1.md`（v15.1.0）。

## Global Constraints

- 区分は境界。`c3c`・`compose.yml`・`Dockerfile.claude`・`entrypoint.sh`・`init-firewall.sh`・`ipv6-firewall.py`・`git-askpass.sh`・`project-images.py`・`lint.sh` を変更する前に `docs/development-invariants.md` の該当節を読む（root `AGENTS.md`）。
- 各 Task の編集後、そのターン内で `./lint.sh` を実行し、終了コード 0・警告ゼロを確かめる。Compose 検証をスキップした場合は `not run` と理由を報告する。
- 挙動を変えたら README.md の該当節を同じコミットで更新する（root `AGENTS.md`）。Task 7 でまとめて書く節も、各 Task の挙動変更と矛盾する記述を残さない（各 Task の Step に README の最小修正を含める）。
- 日本語で書く（コード識別子・コマンドは英語のまま）。コメントは周囲のコード程度の密度で、「なぜ」を書く。
- 第 2 段の原則: 旧名は**検出して案内するだけ**。旧 state・旧 label・旧設定ディレクトリの中身を読んで挙動を決めない（検出に要る存在確認・型確認・label キーの有無の確認だけを行う）。
- 旧名を検出したときの扱い（spec の第 2 段の節）:
  - 旧 env キーが空でない値で設定されている（`.c3c/env` の行・シェル環境のどちらでも）→ `ERROR`（`--check` は `[FAIL]`）。空文字は未設定と同じ。
  - `.claude-container.d` が存在する（型を問わず、`.c3c` の有無も問わず）→ `ERROR`（`--check` は `[FAIL]`）。
  - 旧 state が存在する → `WARNING`（`--check` は `[WARN]`）。新 state だけを使う。
  - `io.c3c.image-layout` が `2` でないイメージ → `ERROR` で `-b` を案内（`--check` は `[FAIL]`）。
  - 由来 label を旧名でだけ持つイメージ（下の「spec が計画に委ねた点の決定」の定義）→ `--check` で `[WARN]`。`--clean-missing` の削除候補にしない。
- 新しいガードは `guard_*` 関数として `guard_fail`/`guard_warn` 経由で通常起動と `--check` の両方に通す（`docs/development-invariants.md` の guard 共用の不変条件）。
- `C3C_*` を readonly にしない（`load_env_file()` の無条件 export と衝突する）。
- `--check` は何も書き込まない。`--clean`（全体）は CLI の記憶（`agent-preferences/`）を消さない。
- 移行の案内に出すパスはクォートする（bash は `printf %q`、Python は `shlex.quote`）。`mv` には `-T` を付ける（宛先が既存ディレクトリでも、旧をその**中へ入れ子にしない**ため。空でない宛先なら失敗し、空のディレクトリなら置き換わる）。
- コンテナ側のファイル（`tests/test_container_paths.py` の対象）には、コメントでも旧名の識別子（`/etc/claude-container`・`.config/claude-container`・`CLAUDE_CONTAINER_`・`claude-container.`）を書かない。説明が要るときは「旧パス」「旧名の env キー」「旧 label」と書く（検査はコメント行も見る）。
- 範囲外（spec）: `CC_*` の内部変数、`_claude-auth-workspace` 接尾辞、upstream の帰属表示と LICENSE、過去の plans/specs、README「旧コマンドからの移行」節の旧コマンド名。`clean_all()` のレガシー共有イメージのコメントは整理してよい。
- 案内文が参照する README の節「旧名 claude-container からの移行（v16）」は Task 7 で作る。Task 1〜7 は 1 つの PR に入れ、途中の Task だけをマージしない（第 2 段は 1 つの MAJOR）。
- コミットは Task ごと。メッセージの末尾に、そのセッションのハーネスが示す attribution 行を付ける。push と PR 作成は持ち主の確認後。

## 第 1 段の未対応 Minor 4 点の扱い（持ち主決定 2026-09-27）

PR #180 本文「未対応の Minor」節の 4 点を、この計画で次のように扱う。

1. rename が `EACCES`・`EPERM`・`EROFS` で失敗すると毎回 ERROR で止まる → **移行コードの削除で対象外**（Task 6 で `rename_noreplace()` と自動移行を削除する。第 2 段は rename しない）。
2. 新 state が壊れた symlink でも「新を使います」と通知する → **Task 6 で解消**。旧 state が残っていて新 state がディレクトリでない（壊れた symlink・ファイル等）場合は、「新 state が使えない」ことを別の文で知らせる。
3. rc 3 の案内の `mv '$old' '$new'` は `$HOME` に `'` を含むと実行できない → **Task 6 で解消**。案内の `mv` は `printf %q` で組み、`-T` を付ける。テストで `'` を含む HOME の案内をそのまま実行して移せることを確かめる。
4. README「旧版へ戻したとき」の記述が、シェル環境だけの `C3C_*` の扱いを区別していない → **Task 7 で解消**。v16 のロールバックの節を、`.c3c/env` に書いた場合とシェル環境だけの場合に分けて書き直す。

## spec が計画に委ねた点の決定

- **第 1 段を経ずに上げた利用者の `--check`（引数なし）**: 「旧 state を移してから再実行する」2 段の案内にする。旧台帳を読み取り専用で参照する案は採らない。理由: 第 2 段の原則（旧名は検出と案内だけ）に沿い、`--check` に旧を読む経路を残さないため。実装は、新の台帳が空で旧の `projects` が空でないファイルとして存在するとき、「起動台帳が空です」に続けて旧台帳がある旨と移行の案内を出すだけ（内容は読まない）。
- **`--clean`（全体）と旧 state**: 第 1 段で入れた「旧 state の承認記録と台帳も消す」処理を削除する。旧 state は検出と案内だけにし、削除は利用者の手に任せる。
- **「由来 label を旧名でだけ持つイメージ」の定義**（`project-images.py` の `legacy_only()`）: `claude-container.project-*` のキーを 1 つ以上持ち、`io.c3c.project-*` のキーを 1 つも持たず、さらに名前ありなら `localhost/<key>_claude-auth-workspace:latest` の形の名前を持つ、名前なしなら `claude-container.project-*` の値のどれかが空でないイメージ。v15.0 以前のプロジェクトイメージ（と `-b` で置き換えられて名前なしになった旧版）がこれに当たる。当たらないもの:
  - v15.1 のイメージ（新旧両方の由来 label）→ 新の組で従来どおり判定する。
  - ビルドの中間イメージ（由来 label は最後の `LABEL` 命令だけなので、`claude-container.asset-hash` 等は持っても `project-*` を持たない）→ 従来どおり名前なしの件数に入れ、ID を出さない（既存の `test_live_dangling_and_intermediates_are_counted_without_id_noise` の契約）。
  - Dockerfile を直接ビルドしたテスト用イメージ（`localhost/claude-test:latest` 等、由来 label の値が空）→ 従来どおり対象外。
  - #118 より前の由来 label 無しのイメージ → label の値を使わない従来の「名前と台帳の照合」（`legacy` 由来）で扱う。第 2 段の「旧 label を由来判定に使わない」に反しない。
- **旧 label だけのイメージの案内**: 元パスが台帳にあるか、ディレクトリとして存在すれば `c3c --clean <shlex.quote したパス>`、それ以外は `podman rmi <ID>`。`--check <dir>` と対象を指定したときは、そのパスの `image_name()` に一致する名前のイメージだけを示す（台帳に無くても示す）。名前なしは、対象を指定した診断でも示す（どのプロジェクトのものか値を読まずに決められないので、見落とさない側に倒す）。

## Review Focus

- `-b` していない v15.1 以前のイメージを v16 の launcher で起動する → compose を 1 回も呼ばず、`ERROR` で `-b` を案内して止まる（承認記録・秘密を旧パスで読むイメージで本起動しない）。Claude・Codex・`--check` の 3 経路。Task 1 の LY-1〜LY-4 と Python の `ImageLayoutGateTests`。
- v16 のイメージを v15.1 の launcher で起動する（ロールバック）→ 承認記録が `/etc/c3c/*` に無いので、MCP と project 設定の確認がもう一度出る。Codex は verify で止まる。黙って承認済みとして通らない（安全側）。Task 2 の `test_codex_entrypoint.py` の既存の「記録なしは停止」と、Task 8 の実機確認。
- シェルの起動ファイルに `export CLAUDE_CONTAINER_NO_FIREWALL=1` だけが残っている利用者 → `ERROR` で止まり、新キー名を案内される（黙ってファイアウォール有効で起動し「無効にならない」と迷わせない）。旧キーがコンテナへ渡っても `entrypoint.sh` は無効化しない。Task 3 の E-L2 と `test_ipv6_entrypoint.py`。
- 旧 state だけがある機械で通常起動する → その起動自身が新 state（起動台帳）を作るので、案内は「セッションを終えてから新を退避し、`mv -T` で旧を移す」の順になり、そのとおり打てば移せる。`--check` は何も書かないので「そのまま `mv -T`」でよい。どちらの案内の `mv` も旧を新の**中**へ入れ子にしない（`-T`）。Task 6 の S2-2・S2-2b・S2-3・`QuotedHomeTests` と `LegacyStateLaunchTests` の「案内どおりに打つ」テスト。
- `c3c --check --clean-missing` を旧 label だけのイメージがある状態で実行する → そのイメージは削除されず、ID と清掃手順が `[WARN]` で示される。v15.1 のイメージ（新旧両方の label）は従来どおり清掃できる。Task 4 の P2-1〜P2-4。

---

### Task 1: イメージの配置 label `io.c3c.image-layout` を確かめるゲート

label を書く `Dockerfile.claude` の変更は Task 2（コンテナ内のパスの変更と同じコミット）で行う。Task 1 のコミットだけでは、`-b` の起動はゲートを見ないので通るが、そのとき作ったイメージは label を持たないので、次の `-b` なしの起動で止まる（途中の Task だけをマージしない、の Global Constraints に従う）。途中の版で作ったイメージの扱いは次のとおりで、どれも安全側になる:
- Task 1 の版で作ったイメージ（パスは旧、label なし）→ Task 2 以降の launcher のゲートで止まる。LY-1・`ImageLayoutGateTests` が「label の無い既存イメージ」を検査する。
- Task 2 以降の版で作ったイメージ（パスは新、label `2`）→ 以降の Task はコンテナ側の配置を変えない（Task 3 は compose が新キーだけを渡し、Task 2 のイメージの `entrypoint.sh` は新キーを優先して読む。Task 4 は label の書き込みだけ）。ゲートを通って正しく動く。

**Files:**
- Modify: `c3c`（定数 25-31 行付近、`guard_codex_image_support()` の直後に新関数、通常起動のガード列の `guard_asset_drift` の直後 3050 行付近、`check_one_project()` のイメージ確認 2690 行付近）
- Modify: `test-build.sh`（fake podman の `image inspect` 619-628 行、IPv6/label の launcher テストの末尾 1720-1750 行付近）
- Modify: `tests/test_c3c_launch.py`（fake podman 61-70 行・build 分岐 75-80 行・bash 版 711 行、新クラス）
- Modify: `tests/test_codex_launch.py`（fake podman 60-72 行と build 分岐）
- Modify: `README.md`（「起動前チェック（`--check`）」節の検査項目に 1 項目）

**Interfaces:**
- Produces: 定数 `IMAGE_LAYOUT_LABEL=io.c3c.image-layout`・`IMAGE_LAYOUT_VERSION=2`（readonly）。
- Produces: `guard_image_layout()`（引数なし。`IMAGE_NAME` のイメージが無いか、通常起動で `-b`（`BUILD=1`）なら何もしない。あって label が `2` でなければ `guard_fail`。`--check` では `[OK]` 行を出す）。
- Produces: fake podman は `io.c3c.image-layout` に既定で `2` を返す（Python は `state['layout']`、build 後は `state.get('build_layout', '2')`。bash 版は `TEST_IMAGE_LAYOUT`、既定 `2`）。以降の Task のテストはこの既定に依存する。

- [ ] **Step 1: 失敗するテストを書く（Python）**

`tests/test_c3c_launch.py` の fake podman（`PODMAN` 文字列内）の `image inspect` 分岐を次にする（`codex-audit-protocol` より前に判定する）:

```python
elif head == 'image inspect':
    if not state.get('image_exists'):
        sys.exit(125)
    fmt = args[args.index('--format') + 1] if '--format' in args else ''
    if 'io.c3c.image-layout' in fmt:
        print(state.get('layout', '2'))
    elif 'io.c3c.codex-audit-protocol' in fmt:
        print(state.get('label', ''))
    elif 'ipv6-support' in fmt:
        print('1')
    else:
        print('')
```

同じ fake の build 分岐（`state['label'] = state.get('build_label', '2')` の行）の直後に `state['layout'] = state.get('build_layout', '2')` を足す。bash 版（`BASH_PODMAN`）の `"image inspect") echo '' ;;` を次に置き換える:

```bash
  "image inspect") case "$*" in *io.c3c.image-layout*) echo 2 ;; *) echo '' ;; esac ;;
```

`tests/test_codex_launch.py` の fake podman にも同じ `io.c3c.image-layout` の分岐（先頭）と build 後の `state['layout']` を足す。

`tests/test_c3c_launch.py` の末尾（`if __name__ == '__main__':` の前）に追加する:

```python
class ImageLayoutGateTests(LaunchCase):
    """改名 第 2 段: io.c3c.image-layout が 2 でない既存イメージでは compose を 1 回も呼ばずに止まる。
    v15.1 以前のイメージは承認記録と秘密を旧パスで読むため、新 compose で本起動させない。"""

    def use_old_image(self):
        self.state['image_exists'] = True
        self.state['layout'] = ''

    def test_claude_launch_rejects_old_image_before_compose(self):
        self.use_old_image()
        result = self.run_c3c('claude', str(self.proj))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('io.c3c.image-layout', result.stderr)
        self.assertIn('-b', result.stderr)
        self.assertEqual(self.compose_calls(), [])

    def test_gate_runs_before_the_host_mcp_prompt(self):
        # ホストの .mcp.json 承認の対話より前に止める（承認に答えさせてから -b を案内しない）。
        self.use_old_image()
        (self.proj / '.mcp.json').write_text('{"mcpServers": {"s": {"command": "x"}}}\n')
        result = self.run_c3c('claude', str(self.proj))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('io.c3c.image-layout', result.stderr)
        self.assertNotIn('[y/N]', result.stdout + result.stderr)

    def test_codex_launch_rejects_old_image_before_preflight(self):
        self.use_old_image()
        self.state['label'] = '2'
        self.approve_codex()
        result = self.run_c3c('codex', str(self.proj))
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.preflight_calls(), [])
        self.assertEqual(self.main_runs(), [])

    def test_rebuild_passes_the_gate(self):
        self.use_old_image()
        result = self.run_c3c('claude', '-b', str(self.proj))
        self.assert_single_run(result, 'claude')
        self.assertEqual(len(self.compose_calls('build')), 1)

    def test_absent_image_is_not_checked(self):
        # 未ビルドなら compose の暗黙ビルドが label 付きで作る。ゲートは既存イメージだけを見る。
        self.state['image_exists'] = False
        result = self.run_c3c('claude', str(self.proj))
        self.assert_single_run(result, 'claude')

    def test_check_reports_fail_without_writing(self):
        self.use_old_image()
        before = self.snapshot(self.home)
        result = self.run_c3c('--check', str(self.proj))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('io.c3c.image-layout', result.stdout + result.stderr)
        self.assertIn('結果: FAIL', result.stdout)
        self.assertEqual(self.snapshot(self.home), before)
```

（`compose_calls`・`preflight_calls`・`main_runs`・`assert_single_run`・`approve_codex`・`snapshot` は `LaunchCase` の既存 helper。`compose_calls()` の引数なしが全 compose 呼び出しを返すことを実装前に確かめ、違えば既存の同等 helper を使う。）

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_c3c_launch.py -k ImageLayoutGate -v`
Expected: `test_claude_launch_rejects_old_image_before_compose`・`test_gate_runs_before_the_host_mcp_prompt`・`test_codex_launch_rejects_old_image_before_preflight`・`test_check_reports_fail_without_writing` が FAIL（ゲートが無いので起動が進む）。残り 2 件は PASS。（`test_gate_runs_before_the_host_mcp_prompt` の `.mcp.json` の形と、非 TTY での `check_mcp_approval` の出力が `[y/N]` を含むことを実装前に確かめ、既存の MCP 承認テストの fixture があればそれに合わせる。）

- [ ] **Step 3: 実装する**

`c3c` の `CLAUDE_PROJECT_AUDIT_PROTOCOL_LABEL=...` の定義の近く（25-31 行付近、既存の readonly 宣言の流儀に合わせる）に追加する:

```bash
# コンテナ内の配置の版（改名 第 2 段）。Dockerfile.claude の LABEL io.c3c.image-layout と一致させる。
IMAGE_LAYOUT_LABEL=io.c3c.image-layout
IMAGE_LAYOUT_VERSION=2
readonly IMAGE_LAYOUT_LABEL IMAGE_LAYOUT_VERSION
```

`guard_codex_image_support()` の直後に追加する:

```bash
# コンテナ内の配置の確認（改名 第 2 段）。v16 の compose は承認記録を /etc/c3c/*、秘密を新パスにだけ載せ、
# v15.1 以前のイメージの entrypoint.sh はそこを読まない。既存イメージの label が対応値でなければ -b を案内して
# 止める（guard_codex_image_support() と同じ型）。未ビルドなら何もしない（compose の暗黙ビルドが label 付きで
# 作る）。通常起動の -b は、この後の明示ビルドで作り直すので見ない（guard_ipv6() と同じ）。通常起動ではガード列で
# 呼び、ホストの MCP 承認の対話・検査用コンテナ・本起動より前に止める。--check では既存イメージの静的診断。
guard_image_layout() {
  [[ "${BUILD:-0}" == 1 && "${CHECK_MODE:-0}" == 0 ]] && return 0
  command -v podman >/dev/null 2>&1 || return 0
  podman image exists "$IMAGE_NAME" 2>/dev/null || return 0
  local layout
  layout=$(podman image inspect --format "{{index .Labels \"$IMAGE_LAYOUT_LABEL\"}}" "$IMAGE_NAME" 2>/dev/null || true)
  if [[ "$layout" != "$IMAGE_LAYOUT_VERSION" ]]; then
    guard_fail "ERROR: イメージ $IMAGE_NAME は c3c v16 のコンテナ内の配置に対応していません（label $IMAGE_LAYOUT_LABEL=${layout:-なし}、必要な値 $IMAGE_LAYOUT_VERSION）。v15 以前にビルドしたイメージは承認記録と秘密を旧パスで読むため、-b で再ビルドしてください。起動を中止します。" ${AGENT_RESELECT_HINT:+"$AGENT_RESELECT_HINT"} || return 1
  fi
  [[ ${CHECK_MODE:-0} -eq 1 ]] && echo "[OK]   イメージの配置: $IMAGE_LAYOUT_LABEL=$layout"
  return 0
}
```

通常起動のガード列（dispatch の `guard_env_gh_token` から始まる列）の末尾、`guard_asset_drift` の直後に 1 行足す（`check_mcp_approval` の対話より前になる）:

```bash
guard_image_layout
```

`check_one_project()` のイメージ確認を次にする（`elif podman image exists ...` の分岐に 1 行足す）:

```bash
  elif podman image exists "$IMAGE_NAME" 2>/dev/null; then
    echo "[OK]   イメージ既ビルド: $IMAGE_NAME"
    guard_image_layout || true
```

- [ ] **Step 4: bash の launcher テストと実イメージの確認を足す**

`test-build.sh` の fake podman の `image inspect` 分岐の先頭（619 行の直後）に追加する:

```bash
    if [[ "\$*" == *io.c3c.image-layout* ]]; then printf '%s\n' "\${TEST_IMAGE_LAYOUT-2}"; fi
```

IPv6/label の launcher テストの関数で、`# L 系（改名 第 1 段）` のブロックの直前に追加する:

```bash
  # LY 系（改名 第 2 段）: io.c3c.image-layout が 2 でない既存イメージは compose を呼ばずに止まる。
  rm -f "$proj/.claude-container.d/env"
  run_launcher TEST_IMAGE_LAYOUT=
  check "LY-1: 配置 label の無い既存イメージは -b を案内して起動を止める（rc=$rc）" \
    bash -c '[ "$1" -ne 0 ] && [ ! -e "$2/compose-args" ] && [[ "$3" == *"io.c3c.image-layout"* && "$3" == *"-b"* ]]' _ "$rc" "$root" "$out"
  run_launcher TEST_IMAGE_LAYOUT=1
  check "LY-2: 配置 label が対応値以外でも止める（rc=$rc）" \
    bash -c '[ "$1" -ne 0 ] && [ ! -e "$2/compose-args" ]' _ "$rc" "$root"
  run_launcher_check TEST_IMAGE_LAYOUT=
  check "LY-3: --check は配置 label の不一致を FAIL にする（rc=$rc）" \
    bash -c '[ "$1" -ne 0 ] && printf "%s" "$2" | grep -q "結果: FAIL"' _ "$rc" "$out"
  run_launcher
  check "LY-4: 配置 label が 2 なら起動する（rc=$rc）" bash -c '[ "$1" -eq 0 ]' _ "$rc"
  printf '%s\n' "$out" >> "$LOG_FILE"
```

（`run_launcher` は毎回 `launcher_sandbox_reset_records` で前回の記録を消す。）

README.md「起動前チェック（`--check`）」節の検査項目の列挙に「イメージの配置 label（`io.c3c.image-layout`。v15 以前のイメージは `[FAIL]` で `-b` を案内）」を足す。

- [ ] **Step 5: テストが通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_c3c_launch.py' -v && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*launch.py' && ./test-build.sh --launcher-only && ./lint.sh`
Expected: すべて PASS、`lint.sh` は終了コード 0・警告ゼロ。

- [ ] **Step 6: コミット**

```bash
git add c3c test-build.sh tests/test_c3c_launch.py tests/test_codex_launch.py README.md
git commit -m "feat: イメージの配置 label io.c3c.image-layout を確かめる起動前のゲートを足す"
```

---

### Task 2: コンテナ内のパスを `/etc/c3c/*` と新しい秘密のパスだけにする

**Files:**
- Modify: `Dockerfile.claude:311-331`（`COPY`・`chmod`・`jq` の `/etc/claude-container/` → `/etc/c3c/`）と、`LABEL io.c3c.codex-audit-protocol="2"` の直後（配置 label）
- Modify: `init-firewall.sh:9,23,24,435`、`ipv6-firewall.py:215`
- Modify: `entrypoint.sh:107,147,149,223,308`
- Modify: `git-askpass.sh:27`
- Modify: `compose.yml:98-105,127,131,133`（旧パスの秘密マウントを削除、承認記録 3 本の target を `/etc/c3c/`）
- Modify: `lint.sh:256,273,274`（`:ro` 検査の target と、旧パスが残っていないことの検査）
- Modify: `tests/test_codex_entrypoint.py:26-32`、`tests/test-lint-compose-checks.sh`（fixture の target）
- Create: `tests/test_container_paths.py`
- Modify: `test-build.sh`（Python テストの一覧 831-840 行付近に 1 行、実イメージの label 確認 2325 行付近に 1 行）
- Modify: README.md（「GitHub トークンの配線」節ほか、コンテナ内のパスの記述）

**Interfaces:**
- Consumes: Task 1 のゲート（旧イメージは新 compose で起動されない）。
- Produces: `Dockerfile.claude` の `LABEL io.c3c.image-layout="2"`。パスの変更と同じコミットに入れる（パスが旧いまま label だけ `2` のイメージを作らない）。
- Produces: コンテナ内の固定パス `/etc/c3c/allowed-domains.txt`・`/etc/c3c/allowed-ports.txt`・`/etc/c3c/github-meta.json`・`/etc/c3c/mcp-approved-hash`・`/etc/c3c/codex-mcp-approved.json`・`/etc/c3c/claude-project-approved.json`・`/home/node/.config/c3c/secrets`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_container_paths.py` を作る:

```python
#!/usr/bin/env python3
"""改名 第 2 段: コンテナ側のファイルが旧名のパス（/etc/claude-container・~/.config/claude-container）と
旧 env キー（CLAUDE_CONTAINER_*）を参照しないこと。v16 の compose はこれらにマウントしないので、参照が
残ると承認記録・秘密・許可リストを黙って読めなくなる。検出と案内のために旧名を扱う launcher（c3c）と
lint.sh の否定検査はこの検査の対象外。"""
from pathlib import Path
import re
import unittest

REPO = Path(__file__).resolve().parents[1]
CONTAINER_SIDE = ('Dockerfile.claude', 'compose.yml', 'compose.ipv6.yml', 'compose.codex-preflight.yml',
                  'compose.plugins-alias.yml', 'compose.shared-home.yml', 'compose.shared-host.yml',
                  'compose.agents.yml', 'compose.codex-plugins.yml', 'entrypoint.sh', 'init-firewall.sh',
                  'ipv6-firewall.py', 'firewall-refresh.py', 'git-askpass.sh', 'codex-launcher.sh',
                  'codex-mcp-audit.py', 'claude-project-audit.py')
# Task 3 で |CLAUDE_CONTAINER_ を、Task 4 で |claude-container\. を足す（各 Task で消す対象だけを検査する）。
LEGACY = re.compile(r'/etc/claude-container|\.config/claude-container')


class ContainerPathTests(unittest.TestCase):
    def test_container_side_files_do_not_reference_legacy_names(self):
        for name in CONTAINER_SIDE:
            with self.subTest(file=name):
                text = (REPO / name).read_text()
                hits = [f'{i}: {line.strip()}' for i, line in enumerate(text.splitlines(), 1) if LEGACY.search(line)]
                self.assertEqual(hits, [])


if __name__ == '__main__':
    unittest.main()
```

（正規表現は Task ごとに広げる。Task 2 はパスだけ、Task 3 で旧 env キー `CLAUDE_CONTAINER_`、Task 4 で旧 label `claude-container\.` を足す。各 Task のコミット時点でこのテストが緑になる。）

`tests/test_codex_entrypoint.py:26-32` の定数を新パスにする:

```python
FIXED_APPROVED = '/etc/c3c/codex-mcp-approved.json'
CLAUDE_APPROVED = '/etc/c3c/mcp-approved-hash'
SECRETS_MOUNT = '/home/node/.config/c3c/secrets'
CLAUDE_PROJECT_APPROVED = '/etc/c3c/claude-project-approved.json'
```

`test-build.sh` の Python テストの一覧（`check "欠落プロジェクトの限定清掃・..."` の行の近く）に追加する:

```bash
  check "コンテナ側のファイルが旧名のパス・env キーを参照しない（改名 第 2 段）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_container_paths.py"
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_container_paths.py' -v; PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_codex_entrypoint.py'`
Expected: `test_container_paths` は `Dockerfile.claude`・`compose.yml`・`entrypoint.sh`・`init-firewall.sh`・`ipv6-firewall.py`・`git-askpass.sh` の subTest で FAIL。`test_codex_entrypoint.py` は定数と entrypoint のパスが食い違って FAIL。

- [ ] **Step 3: 実装する**

パスの置換は次の逐語コマンドで行い、差分を目で確かめる:

```bash
sed -i 's#/etc/claude-container/#/etc/c3c/#g' Dockerfile.claude init-firewall.sh ipv6-firewall.py entrypoint.sh compose.yml
sed -i 's#/home/node/.config/claude-container/secrets#/home/node/.config/c3c/secrets#g' entrypoint.sh git-askpass.sh
git diff --stat
```

`Dockerfile.claude` の `LABEL io.c3c.codex-audit-protocol="2"` の直後に追加する（CACHEBUST を消費する RUN より後、の既存の位置の規則に従う。コメントに旧パスの綴りを書かない）:

```dockerfile
# コンテナ内の配置の版（改名 第 2 段、v16）。launcher の guard_image_layout() は、この label が対応値（2）の
# イメージでだけ本起動・検査用コンテナを起動する。v15.1 以前のイメージは承認記録と秘密を旧パスで読むため、
# v16 の compose（/etc/c3c/* と ~/.config/c3c/secrets だけにマウント）では承認や秘密が黙って欠ける。
# コンテナ内のパスや env の配置を変えたら値を上げ、c3c の IMAGE_LAYOUT_VERSION も揃える。
LABEL io.c3c.image-layout="2"
```

`test-build.sh` の実イメージの label 確認（`check "Claude project 設定ゲートの protocol label" ...` の直後）に追加する:

```bash
check "コンテナ内の配置 label" bash -c '[ "$(podman image inspect --format "{{index .Labels \"io.c3c.image-layout\"}}" "$1")" = 2 ]' _ "$IMAGE"
```

`compose.yml` の秘密のマウントは、旧パスの行と第 1 段のコメント 3 行を削除して次にする:

```yaml
      - ${SECRETS_DIR:-/dev/null}:/home/node/.config/c3c/secrets:ro
```

`entrypoint.sh`・`init-firewall.sh`・`compose.yml` に残る「改名 第 1 段」「旧パス」のコメントは、現在の挙動（新パスだけ）に合わせて書き直す（`grep -n '第 1 段' entrypoint.sh compose.yml init-firewall.sh git-askpass.sh Dockerfile.claude` で洗い出す）。書き直したコメントにも旧名の識別子を綴らない（Global Constraints）。

`lint.sh` の `:ro` 検査を次にする（256 行の for と 273-274 行）:

```bash
    for target in /etc/c3c/codex-mcp-approved.json /etc/c3c/mcp-approved-hash /etc/c3c/claude-project-approved.json /home/node/.gitconfig /home/node/.config/c3c/secrets; do
      compose_mount_is_ro "$target" <<<"$base" || status=1
    done
    # 改名 第 2 段: 旧名のパスへのマウントが残っていないこと（v16 のイメージは旧パスを読まない）。
    if grep -qE '/etc/claude-container/|/home/node/\.config/claude-container/' <<<"$base"; then
      echo "ERROR: compose.yml に旧名のコンテナ内パス（/etc/claude-container・~/.config/claude-container）へのマウントが残っています" >&2
      status=1
    fi
```

```bash
    compose_mount_is_ro /etc/c3c/codex-mcp-approved.json <<<"$merged" || status=1
    compose_mount_is_ro /etc/c3c/claude-project-approved.json <<<"$merged" || status=1
```

`tests/test-lint-compose-checks.sh` の fixture の target を揃える:

```bash
sed -i 's#/etc/claude-container/#/etc/c3c/#g' tests/test-lint-compose-checks.sh
```

README.md のコンテナ内のパスの記述（`grep -n '/etc/claude-container\|config/claude-container' README.md docs/*.md`）を新パスにする。README「旧名 claude-container の識別子からの移行」節の表の「v15.1 系での扱い」列は Task 7 で書き直すので、この Task では触れない。

- [ ] **Step 4: テストが通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_container_paths.py' && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_codex_entrypoint.py' && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_claude_project_entrypoint.py' && bash tests/test-lint-compose-checks.sh && bash tests/test-allowed-domains.sh && ./test-build.sh --launcher-only && ./lint.sh`
Expected: すべて PASS。`lint.sh` は終了コード 0・警告ゼロ。

- [ ] **Step 5: コミット**

```bash
git add Dockerfile.claude init-firewall.sh ipv6-firewall.py entrypoint.sh git-askpass.sh compose.yml lint.sh \
  tests/test_container_paths.py tests/test_codex_entrypoint.py tests/test-lint-compose-checks.sh test-build.sh README.md docs
git commit -m "feat!: コンテナ内のパスを /etc/c3c と ~/.config/c3c/secrets だけにし、配置 label を書く"
```

---

### Task 3: 旧 env キー `CLAUDE_CONTAINER_*` を拒否する

**Files:**
- Modify: `c3c`（`ENV_FILE_ALLOWED_KEYS` 811-822 行、許可リストの説明コメント 790 行、`guard_env_key_renames()` 920-944 行 → `guard_legacy_env_keys()`、通常起動 3039 行と `check_one_project()` 2651 行の呼び出し、`NO_FIREWALL=1` の警告 2159 行）
- Modify: `compose.yml:43-51`、`compose.ipv6.yml:10-11`
- Modify: `entrypoint.sh:58-73`
- Modify: `lint.sh:184-211`（C-1 と IPv6 の needle）
- Modify: `test-build.sh`（E-R1〜R6 → E-L1〜L5、1522-1567 行）
- Modify: `tests/test_ipv6_entrypoint.py`（25・54・80・103-133 行）
- Modify: `README.md`「環境変数」節の表（188-189 行の旧キーの行を削除。E7 が許可リストとの一致を見る）

**Interfaces:**
- Consumes: Task 1 のゲート（旧イメージの `entrypoint.sh` は旧キーしか読まないが、ゲートで起動されない）。
- Produces: `guard_legacy_env_keys()`（引数なし。`CLAUDE_CONTAINER_NO_FIREWALL`・`CLAUDE_CONTAINER_IPV6` のどちらかがシェル環境で空でない、または `$ENV_FILE` に `^KEY=.+` の行があれば `guard_fail`）。
- Produces: compose とコンテナの env は `C3C_NO_FIREWALL`・`C3C_IPV6` だけ。

- [ ] **Step 1: 失敗するテストを書く**

`test-build.sh` の E-R1〜R6 のブロック（`# E-R1〜R6:` から E4 の直前の `printf '%s\n' "$out" >> "$LOG_FILE"` まで）を次に置き換える:

```bash
  # E-L1〜L5: 旧製品名の env キー（CLAUDE_CONTAINER_*）は v16 で廃止（改名 第 2 段）。
  # E-L1: .c3c/env の旧キー → ERROR で新キー名を案内し、compose へ進まない
  printf 'CLAUDE_CONTAINER_NO_FIREWALL=1\n' > "$envf"
  run_launcher
  check "E-L1: env ファイルの旧キーは ERROR（rc=$rc）" \
    bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR:.*CLAUDE_CONTAINER_NO_FIREWALL.*C3C_NO_FIREWALL' && [ ! -e '$root/compose-env' ]" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"
  # E-L2: シェル環境だけの旧キーも ERROR（許可リスト外なので env ファイルの汎用 WARNING には頼れない）
  rm -f "$envf"
  run_launcher CLAUDE_CONTAINER_NO_FIREWALL=1
  check "E-L2: シェル環境の旧キーも ERROR（rc=$rc）" \
    bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR:.*CLAUDE_CONTAINER_NO_FIREWALL.*C3C_NO_FIREWALL' && [ ! -e '$root/compose-env' ]" "$out"
  # E-L3: 新キーだけ → 起動し、compose に新キーだけが渡る。NO_FIREWALL=1 の WARNING は新キー名で出る
  printf 'C3C_NO_FIREWALL=1\n' > "$envf"
  run_launcher
  check "E-L3: 新キーだけは起動する（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] && grep -qxF 'C3C_NO_FIREWALL=1' '$root/compose-env' && ! printf '%s' \"\$0\" | grep -q 'CLAUDE_CONTAINER_'" "$out"
  check "E-L3: 新キーの NO_FIREWALL=1 は WARNING を出す" \
    bash -c "printf '%s' \"\$0\" | grep -q 'WARNING:.*C3C_NO_FIREWALL=1.*無効化'" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"
  # E-L4: 空の旧キーは未設定扱い（ERROR にしない。許可リスト外の汎用 WARNING は出る）
  printf 'CLAUDE_CONTAINER_NO_FIREWALL=\nC3C_NO_FIREWALL=1\n' > "$envf"
  run_launcher
  check "E-L4: 空の旧キーは ERROR にしない（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] && grep -qxF 'C3C_NO_FIREWALL=1' '$root/compose-env'"
  # E-L5: --check は旧キー（シェル環境）を FAIL に集計する
  rm -f "$envf"
  run_launcher_check CLAUDE_CONTAINER_IPV6=0
  check "E-L5: --check は旧キーを FAIL（rc=$rc）" \
    bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR: CLAUDE_CONTAINER_IPV6' && printf '%s' \"\$0\" | grep -q '結果: FAIL'" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"
```

`tests/test_ipv6_entrypoint.py` の 3 つのテスト（103-133 行）を次に置き換え、25・54・80 行の `'CLAUDE_CONTAINER_IPV6': value` / `'true'` を `'C3C_IPV6'` に変える:

```python
    def test_new_key_selects_ipv6(self):
        for env_extra, expected in (({'C3C_IPV6': '1'}, ['--ipv6']), ({'C3C_IPV6': '0'}, []), ({'C3C_IPV6': ''}, [])):
            with self.subTest(env=env_extra):
                response, record = self.run_first_half(env_extra)
                self.assertEqual(response.returncode, 1)
                self.assertEqual(record, ['/usr/local/bin/init-firewall.sh', *expected])

    def test_legacy_keys_are_ignored_on_the_safe_side(self):
        # 改名 第 2 段: 旧キーだけが渡っても IPv6 にも無効化にもしない（ファイアウォール有効・IPv4 のまま）。
        for env_extra in ({'CLAUDE_CONTAINER_IPV6': '1'}, {'CLAUDE_CONTAINER_NO_FIREWALL': '1'}):
            with self.subTest(env=env_extra):
                response, record = self.run_first_half(env_extra)
                self.assertEqual(record, ['/usr/local/bin/init-firewall.sh'])
                self.assertNotIn('エグレスファイアウォールは無効です', response.stderr)

    def test_no_firewall_new_key(self):
        response, record = self.run_first_half({'C3C_NO_FIREWALL': '1'})
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertIsNone(record)
        self.assertIn('エグレスファイアウォールは無効です', response.stderr)
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_ipv6_entrypoint.py' -v; ./test-build.sh --launcher-only`
Expected: `test_legacy_keys_are_ignored_on_the_safe_side` が FAIL（旧キーを fallback で読む）。E-L1・E-L2・E-L5 が FAIL（旧キーは WARNING 付きで通る）。

- [ ] **Step 3: 実装する**

`c3c` の `ENV_FILE_ALLOWED_KEYS` から `CLAUDE_CONTAINER_NO_FIREWALL`・`CLAUDE_CONTAINER_IPV6` の 2 行を削除し、790 行のコメントの「（TZ・C3C_NO_FIREWALL・C3C_IPV6。旧名 CLAUDE_CONTAINER_* は guard_env_key_renames() が新キーへ解決する）」を「（TZ・C3C_NO_FIREWALL・C3C_IPV6。旧名 CLAUDE_CONTAINER_* は v16 で廃止し、guard_legacy_env_keys() が拒否する）」にする。

`guard_env_key_renames()`（コメントを含む 920-944 行）を次に置き換える:

```bash
# 旧製品名の env キー（CLAUDE_CONTAINER_*）は v16 で廃止した（改名 第 2 段。spec
# docs/superpowers/specs/2026-09-27-rename-legacy-identifiers-design.md）。許可リスト外のキーは load_env_file() で
# export されず汎用の「解釈しない」WARNING になるだけなので、guard_legacy_vars() と同じく .c3c/env の行と
# シェル環境の両方を見て、空でない値があれば止めて新キー名を案内する（黙ってファイアウォール有効・IPv4 で
# 起動し、「無効にならない」と迷わせないため）。空文字は未設定と同じ扱い。
guard_legacy_env_keys() {
  local _lek_pair _lek_old _lek_new _lek_rc=0
  for _lek_pair in CLAUDE_CONTAINER_NO_FIREWALL:C3C_NO_FIREWALL CLAUDE_CONTAINER_IPV6:C3C_IPV6; do
    _lek_old="${_lek_pair%%:*}"
    _lek_new="${_lek_pair##*:}"
    if [[ -n "${!_lek_old:-}" ]] || { [[ -n "$ENV_FILE" ]] && grep -qE "^${_lek_old}=.+" "$ENV_FILE" 2>/dev/null; }; then
      guard_fail "ERROR: $_lek_old は v16 で廃止しました（旧製品名の env キー）。$_lek_new に書き換えてください。" \
        "  .c3c/env とシェルの起動ファイル（export $_lek_old=...）の両方を確認してください（README「旧名 claude-container からの移行（v16）」節）。起動を中止します。" || _lek_rc=1
    fi
  done
  return "$_lek_rc"
}
```

通常起動（3039 行）と `check_one_project()`（2651 行）の `guard_env_key_renames` を `guard_legacy_env_keys` に変える（`--check` 側は `|| true` のまま）。

`guard_env_boundary_keys()` の `NO_FIREWALL=1` の検出（2159 行）を新キーだけにする:

```bash
  if nf_key=$(grep -m 1 -oE '^C3C_NO_FIREWALL=1[[:space:]]*$' "$ENV_FILE" 2>/dev/null); then
```

（この行の前後のコメントと `nf_key` を使う警告文が旧キー名に触れていれば、新キー名だけにする。）

`compose.yml:43-51` を次にする（第 1 段のコメントと旧キーの行を削除）:

```yaml
      # エグレス制限の無効化。ホスト側の C3C_NO_FIREWALL（.c3c/env かシェル環境）から補間する。
      C3C_NO_FIREWALL: ${C3C_NO_FIREWALL:-}
      # mode と sysctls/network の不一致を避ける。IPv6用overrideが固定値1へ変える。
      C3C_IPV6: "0"
```

`compose.ipv6.yml` の `CLAUDE_CONTAINER_IPV6: "1"` の行を削除する。

`entrypoint.sh:58-73`（`c3c_resolve_mode_key()` とその 2 回の呼び出し、直前のコメント 3 行）を次に置き換える:

```sh
# 改名 第 2 段（v16）で旧名の env キーの読み取りを削除した（launcher が旧キーを拒否し、compose は新キーだけを
# 渡す）。旧キーだけが渡っても無効化・IPv6 にはしない（ファイアウォール有効・IPv4 のまま＝安全側）。
C3C_IPV6_MODE=${C3C_IPV6:-}
C3C_NO_FIREWALL_MODE=${C3C_NO_FIREWALL:-}
```

`lint.sh` の C-1（184-199 行）を次にする:

```bash
  # 改名 第 2 段（C-1）: コンテナ側の C3C_NO_FIREWALL がホスト側の C3C_NO_FIREWALL から補間され、旧名
  # CLAUDE_CONTAINER_* がコンテナへ渡らないこと。値の引用符は provider 依存なので両方を許す。
  q="['\"]?"
  if nf_on=$(C3C_NO_FIREWALL=1 podman compose -f compose.yml config); then
    grep -qE -- "^[[:space:]]*C3C_NO_FIREWALL: ${q}1${q}[[:space:]]*\$" <<<"$nf_on" \
      || { echo "ERROR: C3C_NO_FIREWALL=1 のとき compose のコンテナ側 C3C_NO_FIREWALL が 1 になりません" >&2; status=1; }
    if grep -q 'CLAUDE_CONTAINER_' <<<"$nf_on"; then
      echo "ERROR: compose.yml に旧名の env キー CLAUDE_CONTAINER_* が残っています" >&2; status=1
    fi
  else
    status=1
  fi
```

IPv6 の needle（210 行）から `"CLAUDE_CONTAINER_IPV6: ${q}1${q}"` を削除する。

README.md「環境変数」節の表から `CLAUDE_CONTAINER_IPV6`・`CLAUDE_CONTAINER_NO_FIREWALL` の 2 行を削除する（E7 が許可リストとの完全一致を見る）。README の他の箇所で `CLAUDE_CONTAINER_` を「使える」と書いている文（`grep -n CLAUDE_CONTAINER_ README.md`）は、Task 7 の移行節を除いて削除か新キーへ直す。

`tests/test_container_paths.py` の正規表現に旧 env キーを足す:

```python
LEGACY = re.compile(r'/etc/claude-container|\.config/claude-container|CLAUDE_CONTAINER_')
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_ipv6_*.py' && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_container_paths.py' && ./test-build.sh --launcher-only && ./lint.sh`
Expected: すべて PASS（E7 を含む）。`lint.sh` は終了コード 0・警告ゼロ。

- [ ] **Step 5: コミット**

```bash
git add c3c compose.yml compose.ipv6.yml entrypoint.sh lint.sh test-build.sh tests/test_ipv6_entrypoint.py tests/test_container_paths.py README.md
git commit -m "feat!: 旧 env キー CLAUDE_CONTAINER_* を拒否し、新キーだけを扱う"
```

---

### Task 4: label を `io.c3c.*` だけにし、旧 label だけのイメージを診断で示す

**Files:**
- Modify: `Dockerfile.claude`（386-392 行・409-411 行・429-437 行の旧 label と第 1 段のコメント）
- Modify: `c3c`（`image_label()` 845-856 行、`guard_asset_drift()` のコメント 2583 行付近）
- Modify: `project-images.py`（15-18 行の定数、`provenance_values()` 163-171 行、`diagnose()` 250-265 行）
- Modify: `test-build.sh`（fake podman 620-625 行、L 系 1722-1750 行）
- Modify: `tests/test_project_images.py`（17-18 行、`item()` 115-120 行、197-240 行、313・526・534 行）
- Modify: `tests/test_container_paths.py`（正規表現に `|claude-container\.` を足す）

**Interfaces:**
- Produces: `image_label <suffix>` は `io.c3c.<suffix>` だけを読む（シグネチャは不変）。
- Produces: `project-images.py` の `provenance_values(labels)` は新の組だけを返す（戻り値の形 `(values, partial)` は不変）。新関数 `legacy_only(item) -> bool`（定義は「spec が計画に委ねた点の決定」節）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_project_images.py`:

- 17 行の `LABEL = 'claude-container.project-'` を `LEGACY_LABEL = 'claude-container.project-'` に改名する。`item()` の既定の `namespace` を `NEW_LABEL` にする。`labels=False` の fixture（`{'claude-container.asset-hash': 'old'}`）は**変えない**。これは由来 label の無い v15.0 以前のイメージと中間イメージの形で、第 2 段でも「旧 label だけのイメージ」には当たらない（定義は `project-*` のキーを要する）。既存の `test_live_dangling_and_intermediates_are_counted_without_id_noise`・`test_legacy_image_matches_ledger_despite_old_labels`・`test_legacy_orphan_is_report_only` はこの fixture のまま通ることを回帰として見る。
- 313・526・534 行の `LABEL + ` を `NEW_LABEL + ` に変える（それぞれ新の組の不正値、新の組が 3 つとも空、直接ビルドの新の組が空、の契約になる）。
- 第 1 段のテストを次のように直す:
  - `test_new_namespace_labels_are_cleaned`: そのまま（既定が新の組になったので重複だが害はない。削除してもよい）。
  - `test_partial_new_group_with_empty_value_is_invalid`: `image = self.item(self.missing, labels=False)` に変え、`image['Labels'][NEW_LABEL + 'metadata'] = ''` を足す（新 metadata のキーだけが空値で存在し、名前と台帳は一致 → invalid で保持。`partial` 判定の回帰を見る）。
  - `test_incomplete_new_group_does_not_borrow_from_complete_old_group`: `image = self.item(self.missing, namespace=LEGACY_LABEL)` に変える（旧の組は完全、新の組は metadata だけ → 保持）。
  - `test_new_group_wins_over_old_group_pointing_elsewhere`: `image = self.item(self.live, namespace=LEGACY_LABEL)` に変える（旧の組は存在するパス、新の組は欠落パス → 新の組で清掃。旧の値を使わないことを見る）。
  - `test_rewritten_ledger_still_finds_old_labeled_image` → `test_rewritten_ledger_still_finds_labeled_image` に改名（既定の新の組で、台帳を書き換えても由来 label で見つかる）。
- 次のテストを足す:

```python
    def v15_image(self, path):
        """v15.1 のイメージ: 新旧両方の由来 label を同じ値で持つ。"""
        image = self.item(path)
        image['Labels'].update({LEGACY_LABEL + k: v for k, v in (
            ('metadata', '1'), ('path', path), ('name', reference_key(path)))})
        return image

    def legacy_only_image(self, path, image_id=IMAGE_A):
        """v15.0 以前のプロジェクトイメージ: 由来 label を旧名でだけ持つ。"""
        image = self.item(path, image_id=image_id, namespace=LEGACY_LABEL)
        image['Labels']['claude-container.asset-hash'] = 'old'
        return image

    # P2-1: 旧 label だけのイメージは、元パスが欠落して台帳にあっても削除しない。ID とクォート済みの --clean の案内を WARN で出す。
    def test_legacy_only_image_is_not_cleaned_and_is_reported(self):
        self.state['images'] = [self.legacy_only_image(self.missing)]
        result = self.run_helper(clean=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.state['images']), 1)
        self.assertIn('[WARN]', result.stdout)
        self.assertIn(IMAGE_A, result.stdout)
        self.assertIn(f'c3c --clean {shlex.quote(self.missing)}', result.stdout)
        # 案内をシェルで分割すると、パスが 1 つの引数に戻る（self.missing は空白を含む）。
        line = next(l for l in result.stdout.splitlines() if 'c3c --clean' in l)
        hint = re.search(r'(c3c --clean .+?) で削除', line).group(1)
        self.assertEqual(shlex.split(hint), ['c3c', '--clean', self.missing])

    # P2-1b: 引用符・シェルの特殊文字を含むパスでも、案内は 1 つの引数へ戻る（貼り付けても別コマンドにならない）。
    def test_legacy_clean_hint_quotes_shell_metacharacters(self):
        tricky = str(Path(self.missing).parent / "it's $(touch x); p")
        self.ledger.write_text(tricky + '\n')
        self.before = self.ledger.read_bytes(), self.ledger.stat().st_mode
        self.state['images'] = [self.legacy_only_image(tricky)]
        result = self.run_helper()
        line = next(l for l in result.stdout.splitlines() if 'c3c --clean' in l)
        hint = re.search(r'(c3c --clean .+?) で削除', line).group(1)
        self.assertEqual(shlex.split(hint), ['c3c', '--clean', tricky])

    # P2-2: 台帳に無い旧 label だけのイメージは podman rmi の案内になる。
    def test_legacy_only_image_outside_ledger_suggests_rmi(self):
        self.ledger.write_text(self.live + '\n')
        self.before = self.ledger.read_bytes(), self.ledger.stat().st_mode
        self.state['images'] = [self.legacy_only_image(self.missing)]
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'podman rmi {IMAGE_A}', result.stdout)

    # P2-3: v15.1 のイメージ（新旧両方の label）は新の組で従来どおり清掃できる。
    def test_v15_image_is_cleaned_by_new_labels(self):
        self.ledger.write_text(self.live + '\n')
        self.before = self.ledger.read_bytes(), self.ledger.stat().st_mode
        self.state['images'] = [self.v15_image(self.missing)]
        result = self.run_helper(clean=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state['images'], [])

    # P2-4: 名前なしの旧版プロジェクトイメージ（-b で置き換えられたもの）は件数に埋もれさせず WARN で示す。
    def test_unnamed_legacy_only_image_is_reported(self):
        image = self.legacy_only_image(self.missing)
        image['Names'] = []
        self.state['images'] = [image]
        result = self.run_helper()
        self.assertIn('[WARN]', result.stdout)
        self.assertIn(f'podman rmi {IMAGE_A}', result.stdout)

    # P2-5: 対象を指定した診断では、台帳に無くても名前がその対象のイメージなら示す。
    def test_targeted_check_reports_legacy_image_outside_ledger(self):
        self.ledger.write_text(self.live + '\n')
        self.before = self.ledger.read_bytes(), self.ledger.stat().st_mode
        self.state['images'] = [self.legacy_only_image(self.missing)]
        result = self.run_helper(paths=[self.missing])
        self.assertIn('[WARN]', result.stdout)
        self.assertIn(IMAGE_A, result.stdout)

    # P2-5b: 対象を指定した診断でも、名前なしの旧版イメージは示す（どの対象のものかは値を読まずに決められないので、対象を問わず示す）。
    def test_targeted_check_reports_unnamed_legacy_image(self):
        image = self.legacy_only_image(self.missing)
        image['Names'] = []
        self.state['images'] = [image]
        result = self.run_helper(paths=[self.live])
        self.assertIn('[WARN]', result.stdout)
        self.assertIn(f'podman rmi {IMAGE_A}', result.stdout)

    # P2-6: 中間イメージ（新旧の単独 label だけ、由来 label なし、名前なし）は ID を出さずに件数に入れる。
    def test_v15_intermediate_images_are_counted_without_id_noise(self):
        image = self.item(self.live, labels=False)
        image['Labels']['io.c3c.asset-hash'] = 'x'
        image['Names'] = []
        self.state['images'] = [image]
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(IMAGE_A, result.stdout)
```

（先頭の import に `re`・`shlex`・`Path` が無ければ足す。P2-1b の `tricky` は `self.missing` と同じ親（実在する）の下の存在しないパスなので、`path_state` は欠落になり、台帳にあるので `c3c --clean` の案内になる。`IMAGE_A` が fake の `Id` の完全形と同じ文字列で出力に載ることを確かめる。`parse_image()` が ID を正規化するなら、期待値を正規化後の値に合わせる。P2-5 の `paths` は `run_helper` の既存の引数。）

`test-build.sh` の fake podman の `image inspect` 分岐のうち、`*claude-container.ipv6-support*` の行から `*claude-container.base-image*` の行までの 6 行（内容で特定する。Task 1 で先頭に足した `io.c3c.image-layout` の行と、その後の `claude-project-audit-protocol` の行は残す）を次の 4 行にする。旧 label を読んだら記録する:

```bash
    if [[ "\$*" == *claude-container.* ]]; then printf '%s\n' "\$*" >> "$root/legacy-label-reads"; fi
    if [[ "\$*" == *io.c3c.ipv6-support* ]]; then printf '%s\n' "\${TEST_IPV6_SUPPORT-1}"; fi
    if [[ "\$*" == *io.c3c.asset-hash* ]]; then printf '%s\n' "\${TEST_ASSET_HASH-}"; fi
    if [[ "\$*" == *io.c3c.base-image* ]]; then printf '%s\n' "\${TEST_BASE_IMAGE-}"; fi
```

L 系（`# L 系（改名 第 1 段）` から関数末尾の `launcher_sandbox_cleanup` の直前まで）を次に置き換える:

```bash
  # L2 系（改名 第 2 段）: 単独の label は io.c3c.* だけを読み、旧 label へ fallback しない。
  rm -f "$root/legacy-label-reads"
  run_launcher
  local real_hash real_base
  real_hash=$(sed -n 's/^ASSET_HASH=//p' "$root/compose-env")
  real_base=$(sed -n 's/^BASE_IMAGE=//p' "$root/compose-env")
  run_launcher TEST_ASSET_HASH="$real_hash" TEST_BASE_IMAGE="$real_base"
  check "L2-1: 新 label が一致すればドリフトの WARNING なし" \
    bash -c "! printf '%s' \"\$0\" | grep -qE '境界アセット.*変更されています|ハッシュラベルがありません|ベースイメージの設定'" "$out"
  run_launcher TEST_ASSET_HASH= TEST_BASE_IMAGE="$real_base"
  check "L2-2: 新 label が空ならハッシュラベルなしの WARNING（旧 label へ fallback しない）" \
    bash -c "printf '%s' \"\$0\" | grep -q 'ハッシュラベルがありません'" "$out"
  run_launcher TEST_ASSET_HASH="$real_hash" TEST_BASE_IMAGE=bogus
  check "L2-3: base-image の新 label が違えば WARNING" \
    bash -c "printf '%s' \"\$0\" | grep -q 'ベースイメージの設定.*異なります'" "$out"
  run_launcher_check
  check "L2-4: 通常起動と --check は旧 label を読まない" bash -c "[ ! -e '$root/legacy-label-reads' ]"
  printf '%s\n' "$out" >> "$LOG_FILE"
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_project_images.py' -v; ./test-build.sh --launcher-only`
Expected: P2-1・P2-1b（旧 label の組で清掃される、案内が無い）、P2-2・P2-4・P2-5・P2-5b（案内が無い）が FAIL。P2-3・P2-6 と既存の中間イメージのテストは PASS。L2-2（旧 label の fallback はテスト変数が無いので空＝通ることもある）と L2-4（`image_label` が旧 label を読む）が FAIL。

- [ ] **Step 3: 実装する**

`Dockerfile.claude` から `claude-container.*` の label を削除し、第 1 段のコメント（386-387 行）を削除する。3 か所は次の形になる:

```dockerfile
LABEL io.c3c.asset-hash="${ASSET_HASH}"
LABEL io.c3c.ipv6-support="1"
...
LABEL io.c3c.base-image="${BASE_IMAGE}"
...
LABEL io.c3c.project-metadata="${CC_PROJECT_METADATA}" \
      io.c3c.project-path="${CC_PROJECT_PATH}" \
      io.c3c.project-name="${CC_PROJECT_NAME}"
```

`c3c` の `image_label()` を次にする（コメントを含めて置き換える）:

```bash
# 単独のキーの image label（io.c3c.<suffix>）を読む。inspect の index は欠落キーにも空文字を返すので、
# 欠落と空値は区別しない。旧名 claude-container.* は v16 で読まない（改名 第 2 段。v15 以前のイメージは
# guard_image_layout() が止める）。由来 label（project-*）は組単位で選ぶので project-images.py が扱う。
image_label() {
  podman image inspect --format "{{index .Labels \"io.c3c.$1\"}}" "$IMAGE_NAME" 2>/dev/null || true
}
```

（従来は `printf '%s'` で末尾改行を落としていた。呼び出し側は `$(image_label ...)` のコマンド置換で末尾改行が落ちるので同じ結果になる。）`guard_asset_drift()` のコメント「（Dockerfile.claude の io.c3c.base-image。旧イメージは旧名）」から「旧イメージは旧名」を削除する。

`project-images.py`:

```python
NEW_PREFIX = 'io.c3c.project-'
# 旧名の由来 label（v15.0 以前のプロジェクトイメージ）。由来判定・削除判定には使わず、検出して案内するだけ
# （改名 第 2 段）。
LEGACY_PREFIX = 'claude-container.project-'
SUFFIXES = ('metadata', 'path', 'name')
NEW_LABELS = tuple(NEW_PREFIX + suffix for suffix in SUFFIXES)
```

（`LEGACY_LABELS` は削除する。先頭の import に `shlex` を足す。）

```python
def provenance_values(labels):
    """由来 label（io.c3c.project-*）の組を返す。組のキーが一部だけなら partial=True（値が空でも、台帳の
    legacy 照合へ落とさず invalid にする）。三つとも揃って空なのは直接ビルドの既存契約で、従来どおり扱う。"""
    present = [key in labels for key in NEW_LABELS]
    return [labels.get(key, '') for key in NEW_LABELS], any(present) and not all(present)


def legacy_only(item):
    """由来 label を旧名でだけ持つプロジェクトイメージ（c3c v15.0 以前）。旧の値はイメージの種類の判定
    （空か否か）にだけ使い、パスや由来の根拠にはしない。当たらないもの: 新の由来 label を持つ v15.1 の
    イメージ、由来 label の無い中間イメージ・#118 より前のイメージ、値が空の直接ビルド、プロジェクト名で
    ない名前だけのイメージ。"""
    labels = item['labels']
    legacy = [k for k in labels if k.startswith(LEGACY_PREFIX)]
    if not legacy or any(k in labels for k in NEW_LABELS) or not any(labels[k] for k in legacy):
        return False
    return not item['names'] or any(IMAGE_NAME.fullmatch(n) for n in item['names'])
```

`diagnose()` のループの先頭（`if args.project and not paths.intersection(selected): continue` の**前**）に追加する。対象の絞り込みより前に置くのは、旧 label の値を読まないので `paths` が台帳の名前一致だけになり、対象を指定した診断で台帳に無いイメージが先に `continue` されてしまうため:

```python
        if legacy_only(item):
            # 旧 label の値は読まない。名前が台帳・指定対象のパスの image_name() と一致すれば、そのパスを案内に使う。
            named = sorted(p for p in set(ledger) | set(args.project) if image_name(p) in item['names'])
            if args.project and item['names'] and not set(named) & selected:
                continue                                   # 名前なしは、どの対象のものか値を読まずに決められないので常に示す
            path = named[0] if len(named) == 1 else None
            if path and (path in ledger or path_state(path) == 'directory'):
                hint = f'c3c --clean {shlex.quote(path)}'
            else:
                hint = f'podman rmi {item["id"]}'
            report('WARN', f'旧 label だけのイメージ（c3c v15.0 以前）を保持します: {item["id"]} '
                           f'名前={item["names"]!r}。不要なら {hint} で削除してください'
                           f'（中身は podman image inspect {item["id"]}）。')
            continue
```

名前なしの `relevant` 判定から旧前方一致を外す（旧版のプロジェクトイメージは上の `legacy_only` で扱い済み。残る旧前方一致は中間イメージ等で、従来どおり件数に入れるために `history` の名前一致だけで足りるかを確かめる。足りなければ `any(k.startswith('claude-container.') for k in item['labels'])` を残す — 件数に入れるだけで値は使わない）:

```python
        else:
            relevant = (any(k in item['labels'] for k in NEW_LABELS)
                        or any(IMAGE_NAME.fullmatch(n) for n in item['history']))
```

（`provenance()` の値は新の組だけなので、`legacy_only` に当たらないイメージでも旧 label の値は由来判定に使われない。）

`tests/test_container_paths.py` の正規表現に旧 label の `|claude-container\.` を足す:

```python
LEGACY = re.compile(r'/etc/claude-container|\.config/claude-container|CLAUDE_CONTAINER_|claude-container\.')
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_project_images.py' -v && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_container_paths.py' && ./test-build.sh --launcher-only && ./lint.sh`
Expected: すべて PASS。`lint.sh` は終了コード 0・警告ゼロ。

- [ ] **Step 5: コミット**

```bash
git add Dockerfile.claude c3c project-images.py test-build.sh tests/test_project_images.py tests/test_container_paths.py
git commit -m "feat!: label を io.c3c.* だけにし、旧 label だけのイメージを診断で示す"
```

---

### Task 5: 旧設定ディレクトリ `.claude-container.d/` を拒否する

**Files:**
- Modify: `c3c`（`select_project_conf_dir()` とその説明コメント 581-640 行、`ENV_FILE` 周辺のコメント 777・2150・3023 行）
- Modify: `.gitignore`（4-10 行）
- Modify: `tests/test_c3c_launch.py:140`、`tests/test_codex_launch.py:134`、`tests/test_project_images.py:464`、`test-build.sh`（`.claude-container.d` の fixture 全部）
- Modify: `tests/test_c3c_config.py`（配置表の docstring、`ConfigCase` の layout helper、旧名を採用する前提のテスト）
- Modify: README.md（「利用側プロジェクトの設定」節の旧名の記述。「旧 `.claude-container.d/` からの移行」節は Task 7）

**Interfaces:**
- Produces: `select_project_conf_dir()` は `$WORKING_DIR/.claude-container.d` が存在すれば（`-e` または `-L`）`guard_fail`。それ以外は `.c3c` だけを見る（なし → `.c3c` を参照元、ディレクトリ → 採用、ディレクトリでない → `guard_fail`）。戻り値と `PROJECT_CONF_DIR` の readonly の位置は不変。
- Produces: テストの fixture の設定ディレクトリは `.c3c`（`LaunchCase.conf`）。

- [ ] **Step 1: fixture を `.c3c` へ移す（挙動は変えない）**

新名は第 1 段で既に採用されるので、fixture の置換だけでは挙動が変わらない。逐語で次を実行し、差分を確かめる:

```bash
sed -i 's#\.claude-container\.d#.c3c#g' test-build.sh tests/test_codex_launch.py tests/test_project_images.py
sed -i "s#self.proj / '.claude-container.d'#self.proj / '.c3c'#" tests/test_c3c_launch.py
git diff --stat
grep -n 'claude-container\.d' test-build.sh tests/*.py
```

`test-build.sh` のログ見出し（2407 行 `## .claude-container.d によるパッケージ上書き`、2591 行）とチェック名（2624・2628 行）も置換で `.c3c` になる。置換後に `grep` で残るのは `tests/test_c3c_config.py` だけのはず。

Run: `./test-build.sh --launcher-only`
Expected: `test_c3c_config.py` 以外は PASS（`--launcher-only` は `test_c3c_config.py` も実行する。`ConfigCase` が `self.legacy.rename(self.new)` で旧名の fixture を前提にするので、この時点で FAIL するものがある。Step 2 で直す）。

- [ ] **Step 2: 失敗するテストを書く（`tests/test_c3c_config.py`）**

docstring の配置表を第 2 段の契約にする:

```text
| `.c3c` | `.claude-container.d` | 通常起動 / check |
|---|---|---|
| なし | なし | `.c3c` を参照元として既存 fallback。directory は作らない |
| directory | なし | `.c3c` を採用 |
| 任意 | 存在（型を問わない） | ERROR（v16 で旧名の読み取りを廃止。`mv -T` を案内） |
| file / dangling link 等 | なし | ERROR、ビルドや env 読込より前に停止 |
```

`ConfigCase` の helper を、fixture が既に `.c3c` である前提に直す:

```python
    def setUp(self):
        super().setUp()
        self.legacy = self.proj / LEGACY
        self.new = self.proj / NEW
        self.build_context = self.runner / '.build-context'

    def use_new_layout(self):
        return self.new

    def use_legacy_layout(self):
        """旧名だけの配置（第 2 段では ERROR になる配置）。"""
        self.new.rename(self.legacy)
        self.conf = self.legacy
        return self.legacy

    def use_no_layout(self):
        for item in self.new.iterdir():
            item.unlink()
        self.new.rmdir()
```

旧名を採用する前提のテストを次の方針で書き換える（テスト名で特定する）:

- `test_legacy_layout_is_adopted_with_migration_warning` → 次の `test_legacy_layout_is_rejected_before_env_and_build` に置き換える。
- `test_both_directories_are_rejected_before_env_is_read_even_with_identical_content`・`test_two_links_to_the_same_directory_are_still_both_present` → 期待（ERROR・env を読まない）は同じ。案内文の照合があれば新しい文言（`v16`・`mv -T`）に合わせる。
- `test_symlink_to_a_directory_is_accepted_for_either_name` → 新名の symlink だけを受け付け、旧名の symlink は ERROR にする 2 つの subTest にする。
- `test_file_or_dangling_link_is_an_error_before_env_and_build` → 旧名の file・dangling link の subTest は「旧名の存在で ERROR」の文言に合わせる。旧名のエラー文は旧名の絶対パス（`$legacy_path`）を含むが、`.c3c` 側は相対名でしか出さないので、`'legacy dir + .c3c file'` 等で `assertIn(str(target))` が `.c3c` の絶対パスを期待している subTest は、旧名の絶対パスか `LEGACY` の照合に変える。
- `ResolverConsistencyTests.test_same_inputs_stage_identically_and_hash_matches_between_layouts` → 新旧配置の比較は成り立たないので削除する（新名の staging と hash は `BuildInputDefaultTests` が見る）。
- `BuildInputDefaultTests` の「新旧配置それぞれで」のループ → 新名だけにする。
- `run_legacy`（旧名の外部 symlink 経由の起動）を使うテストは、入口の契約として残す（設定ディレクトリの旧名とは別物）。

追加するテスト:

```python
    def test_legacy_layout_is_rejected_before_env_and_build(self):
        # 改名 第 2 段: 旧名 .claude-container.d は、.c3c の有無に関わらず存在するだけで ERROR。env を読まず、
        # ビルドへも進まない。案内は mv -T（.c3c が既にあっても中へ入れない）。
        self.make_env(self.use_legacy_layout(), f'{ENV_PROBE}=/x\n')
        # agent を明示する（未指定・非 TTY だと select_c3c_agent が設定ディレクトリの選択より前に止まる）。
        for entry, runner, args in (('c3c', self.run_c3c, ['claude', str(self.proj)]),
                                    ('legacy', self.run_legacy, ['claude', str(self.proj)])):
            with self.subTest(entry=entry):
                result = runner(*args)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(LEGACY, result.stderr)
                self.assertIn('mv -T', result.stderr)
                self.assert_env_not_read(result.stdout + result.stderr)
                self.assertEqual(self.compose_calls(), [])
        result = self.run_check('c3c', self.proj)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('[FAIL]', result.stdout)
        self.assert_env_not_read(result.stdout + result.stderr)

    def test_legacy_directory_is_rejected_even_next_to_new(self):
        self.make_env(self.new)
        self.legacy.mkdir()
        result = self.run_c3c('claude', str(self.proj))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(LEGACY, result.stderr)
```

（`run_legacy` に渡す引数は、既存テストが旧名 symlink 経由の Claude 起動に使っている形に合わせる。）

- [ ] **Step 3: テストが失敗することを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_c3c_config.py' -v`
Expected: `test_legacy_layout_is_rejected_before_env_and_build` が FAIL（旧名だけは WARNING 付きで採用される）。

- [ ] **Step 4: 実装する**

`select_project_conf_dir()` の説明コメント（581-596 行）と本体を次に置き換える（`PROJECT_CONF_NEW_NAME`・`PROJECT_CONF_LEGACY_NAME` の定数は残す）:

```bash
# プロジェクト設定ディレクトリの選択。起動 checkout 直下の .c3c を採用パスとして PROJECT_CONF_DIR に返してから
# readonly にする。旧名 .claude-container.d は v16 で読み取りを廃止した（改名 第 2 段）。存在すれば型も .c3c の
# 有無も問わず止めて移行を案内する（黙って .c3c 側だけを読むと、旧名に書いた設定が効かないことに気づけない）。
#   .c3c なし: .c3c を参照元にする（同梱の既定値へ fallback。directory は作らない）
#   .c3c が directory（または directory への symlink）: 採用
#   .c3c が directory へ解決できない（file・リンク先の無い symlink・file への symlink）: ERROR
# 存在判定は -e だけでなく -L でも行う（dangling link も「配置あり」）。呼出名では結果を変えない。
# 呼ぶ位置は通常起動・--check とも load_env_file() より前、--clean の分岐より後。--check では失敗時に呼び出し元が
# return 20 し、env・resolver・hash・ガードへ進まない。readonly は結果を返した後に置く（#39）。
PROJECT_CONF_NEW_NAME=.c3c
PROJECT_CONF_LEGACY_NAME=.claude-container.d
readonly PROJECT_CONF_NEW_NAME PROJECT_CONF_LEGACY_NAME
select_project_conf_dir() {
  local new_path="$WORKING_DIR/$PROJECT_CONF_NEW_NAME" legacy_path="$WORKING_DIR/$PROJECT_CONF_LEGACY_NAME" kind
  if [[ -e "$legacy_path" || -L "$legacy_path" ]]; then
    guard_fail "ERROR: 旧名の設定ディレクトリ $legacy_path があります（c3c v16 で旧名の読み取りを廃止しました）。" \
      "  $PROJECT_CONF_NEW_NAME が無ければ、起動していない状態でプロジェクト直下で mv -T -- $PROJECT_CONF_LEGACY_NAME $PROJECT_CONF_NEW_NAME（Git 追跡対象なら git mv）を実行し、.gitignore の $PROJECT_CONF_LEGACY_NAME/env も $PROJECT_CONF_NEW_NAME/env に書き換えてください。" \
      "  $PROJECT_CONF_NEW_NAME が既にある場合は、中身を確かめてから旧名をプロジェクトの外へ退避してください（README「旧名 claude-container からの移行（v16）」節）。起動を中止します。" || return 1
  fi
  if [[ ! -e "$new_path" && ! -L "$new_path" ]]; then
    PROJECT_CONF_DIR="$new_path"
    readonly PROJECT_CONF_DIR
    [[ ${CHECK_MODE:-0} -eq 1 ]] && echo "[INFO] 設定ディレクトリ: なし（$PROJECT_CONF_NEW_NAME を参照元にし、同梱の既定値を使います）"
    return 0
  fi
  if [[ ! -d "$new_path" ]]; then
    kind="ディレクトリではありません"
    if [[ -L "$new_path" && ! -e "$new_path" ]]; then
      kind="リンク先の無い symlink です"
    elif [[ -L "$new_path" ]]; then
      kind="ディレクトリ以外を指す symlink です"
    fi
    guard_fail "ERROR: 設定ディレクトリ $new_path は$kind。ディレクトリ（またはディレクトリへの symlink）に直すか取り除いてください。起動を中止します。" || return 1
  fi
  PROJECT_CONF_DIR="$new_path"
  readonly PROJECT_CONF_DIR
  [[ ${CHECK_MODE:-0} -eq 1 ]] && echo "[OK]   設定ディレクトリ: $PROJECT_CONF_DIR"
  return 0
}
```

（`.c3c` の名前はリテラルなので `%q` は不要。案内の `mv -T` はプロジェクト直下で打つ相対名にしている。）

`c3c` の 777・2150・3023 行のコメントの「（.c3c/env、旧 .claude-container.d/env）」「（.c3c / 旧 .claude-container.d）」から旧名を外す。

`.gitignore` は、4 行目のコメントの「（新名 .c3c/env、旧名 .claude-container.d/env。両方は置かない）」を「（.c3c/env）」にし、10 行目の `.claude-container.d/env` の行を削除する。5-9 行の他のコメント（`packages.txt` 等はコミット対象、自身の設定も `.c3c/`、サンプルの場所）は残す。

README.md「利用側プロジェクトの設定」節の「旧名 `.claude-container.d/` も移行期間中は読める」の類の文（`grep -n '移行期間' README.md`）を、「旧名 `.claude-container.d/` は v16 で読み取りを廃止した（存在すると起動を止める）」にする。README 冒頭 7 行・176 行も同じ。

- [ ] **Step 5: テストが通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_c3c_config.py' -v && ./test-build.sh --launcher-only && ./lint.sh`
Expected: すべて PASS。`lint.sh` は終了コード 0・警告ゼロ。

- [ ] **Step 6: コミット**

```bash
git add c3c .gitignore test-build.sh tests/test_c3c_launch.py tests/test_codex_launch.py tests/test_project_images.py tests/test_c3c_config.py README.md
git commit -m "feat!: 旧設定ディレクトリ .claude-container.d を拒否して移行を案内する"
```

---

### Task 6: state の自動移行を削除し、旧 state は検出と案内だけにする

**Files:**
- Modify: `c3c`（`rename_noreplace()`・`resolve_state_dir()` 300-381 行、`clean_all()` 400-418 行、`run_check_mode()` 2829-2855 行）
- Delete: `tests/test_state_migration.py`
- Create: `tests/test_legacy_state.py`
- Modify: `tests/test_c3c_launch.py`（`StateMigrationLaunchTests` 1011-1090 行 → `LegacyStateLaunchTests`）
- Modify: `test-build.sh:835`（Python テストの一覧）
- Modify: README.md「変更後の確認」節の state の段落

**Interfaces:**
- Produces: `resolve_state_dir()`（引数なし。`CC_STATE_DIR` は常に `$HOME/.local/state/c3c`、`CC_LEGACY_STATE_DIR` は `$HOME/.local/state/claude-container`（検出専用）、`CC_STATE_NOTICE` は旧が存在するときの案内文、無ければ空。何も書かない）。通常起動では案内を `WARNING:` で stderr に出す（`--check` は `run_check_mode()` が `[WARN]` で出す、従来どおり）。
- Removes: `rename_noreplace()`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_state_migration.py` を削除し（`git rm`）、`tests/test_legacy_state.py` を作る:

```python
#!/usr/bin/env python3
"""旧 state（~/.local/state/claude-container）の検出と案内（改名 第 2 段）の関数単位の回帰試験。

c3c から resolve_state_dir() を抽出し、隔離 HOME で実行する。第 2 段は旧 state を読まない・移さない・消さない。
"""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


def extract(name):
    text = (REPO / 'c3c').read_text()
    start = text.index(f'\n{name}() {{\n') + 1
    end = text.index('\n}\n', start) + 3
    return text[start:end]


def snapshot(root):
    result = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            st = os.lstat(path)
            result[str(path)] = (st.st_mode, st.st_size, os.readlink(path) if path.is_symlink() else None)
    return result


class LegacyStateTests(unittest.TestCase):
    def setUp(self, home_name='home'):
        self.temp = tempfile.TemporaryDirectory(prefix='cc-state-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / home_name
        self.base = self.home / '.local/state'
        self.base.mkdir(parents=True)
        self.old = self.base / 'claude-container'
        self.new = self.base / 'c3c'

    def run_resolve(self, check=0):
        script = '\n'.join([extract('resolve_state_dir'), 'resolve_state_dir',
                            'printf "DIR=%s\\nNOTICE=%s\\n" "$CC_STATE_DIR" "$CC_STATE_NOTICE"'])
        env = {'HOME': str(self.home), 'PATH': os.environ['PATH'], 'CHECK': str(check), 'CLEAN': '0',
               'LC_ALL': 'C.UTF-8'}
        return subprocess.run(['bash', '-c', 'set -euo pipefail\n' + script], env=env, capture_output=True, text=True)

    def fields(self, result):
        return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)

    def make_old(self):
        (self.old / 'mcp-approvals').mkdir(parents=True)
        (self.old / 'projects').write_text('/p\n')

    def mv_commands(self, notice):
        # 案内文の mv -T を順に取り出す。パスは %q 済みなので、空白は \ でエスケープされている（Step 3）。
        token = r'(?:\\.|[^\s\\])+'
        commands = re.findall(rf'mv -T -- {token} {token}', notice)
        self.assertTrue(commands, notice)
        return commands

    def run_commands(self, commands):
        return [subprocess.run(['bash', '-c', c], capture_output=True).returncode for c in commands]

    # S2-1: 旧なし → 新、案内なし
    def test_no_old_uses_new_silently(self):
        r = self.run_resolve()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fields(r), {'DIR': str(self.new), 'NOTICE': ''})

    # S2-2: 旧だけの --check → 新を使い、旧は動かさない。案内の mv -T（1 つ）をそのまま打てば移る
    def test_old_only_check_hint_works(self):
        self.make_old()
        before = snapshot(self.home)
        r = self.run_resolve(check=1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(snapshot(self.home), before)
        f = self.fields(r)
        self.assertEqual(f['DIR'], str(self.new))
        commands = self.mv_commands(f['NOTICE'])
        self.assertEqual(len(commands), 1)
        self.assertEqual(self.run_commands(commands), [0])
        self.assertEqual((self.new / 'projects').read_text(), '/p\n')

    # S2-2b: 旧だけの通常起動 → 起動が新を作る前提で「新を退避 → 旧を移す」の 2 手を案内し、そのとおり打てば移る
    def test_old_only_launch_hint_works_after_new_is_created(self):
        self.make_old()
        r = self.run_resolve()
        commands = self.mv_commands(self.fields(r)['NOTICE'])
        self.assertEqual(len(commands), 2)
        self.new.mkdir()                                  # 起動台帳の記録が新を作った状態
        (self.new / 'projects').write_text('/q\n')
        self.assertEqual(self.run_commands(commands), [0, 0])
        self.assertEqual((self.new / 'projects').read_text(), '/p\n')
        self.assertFalse((self.new / 'claude-container').exists())

    # S2-3: 新旧の両方 → 新を使う。旧を移す mv -T だけを先に打っても、旧を新の中へ入れない（失敗する）
    def test_both_present_hint_never_nests_old_into_new(self):
        self.make_old()
        self.new.mkdir()
        (self.new / 'projects').write_text('/q\n')
        r = self.run_resolve()
        f = self.fields(r)
        self.assertEqual(f['DIR'], str(self.new))
        self.assertIn('残っています', f['NOTICE'])
        commands = self.mv_commands(f['NOTICE'])
        self.assertNotEqual(self.run_commands(commands[-1:]), [0])
        self.assertFalse((self.new / 'claude-container').exists())
        self.assertEqual(self.run_commands(commands), [0, 0])
        self.assertEqual((self.new / 'projects').read_text(), '/p\n')

    # S2-4（第 1 段 Minor 2）: 新が壊れた symlink なら「使えない」と知らせる
    def test_dangling_new_is_reported_as_unusable(self):
        self.make_old()
        self.new.symlink_to(self.base / 'nowhere')
        f = self.fields(self.run_resolve())
        self.assertIn('ディレクトリではない', f['NOTICE'])
        self.assertNotIn('を使います', f['NOTICE'])

    # S2-6: 旧がファイルでも検出する（型を問わない）
    def test_old_file_is_detected(self):
        self.old.write_text('x')
        self.assertIn(str(self.old), self.fields(self.run_resolve())['NOTICE'])

    # S2-7: --check でも何も書かない
    def test_check_writes_nothing(self):
        self.make_old()
        before = snapshot(self.home)
        self.run_resolve(check=1)
        self.assertEqual(snapshot(self.home), before)


class QuotedHomeTests(LegacyStateTests):
    # S2-5（第 1 段 Minor 3）: HOME に ' と空白を含んでも、案内の mv -T をそのまま打てば移る
    def setUp(self):
        super().setUp(home_name="it's home")


if __name__ == '__main__':
    unittest.main()
```

（`QuotedHomeTests` は親の全テストを `'` と空白を含む HOME で再実行する。S2-2・S2-2b・S2-3 は案内の `mv -T` をそのまま bash に渡して移せることを見るので、`%q` のクォートが壊れていれば失敗する。S2-3 は、旧を移す 1 手だけを先に打つと新が空でないので失敗し、旧が新の中へ入らないことも見る。）

`tests/test_c3c_launch.py` の `StateMigrationLaunchTests` を次に置き換える:

```python
class LegacyStateLaunchTests(LaunchCase):
    """改名 第 2 段: 旧 state は読まない・移さない・消さない。検出して案内するだけ。"""

    def make_legacy_state(self):
        legacy = self.home / '.local/state/claude-container'
        (legacy / 'agent-preferences').mkdir(parents=True, mode=0o700)
        (legacy / 'projects').write_text(str(self.proj) + '\n')
        return legacy

    def test_normal_launch_warns_and_leaves_legacy_untouched(self):
        legacy = self.make_legacy_state()
        before = self.snapshot(legacy)
        result = self.run_c3c('claude', str(self.proj))
        self.assert_single_run(result, 'claude')
        self.assertIn('WARNING: 旧 state', result.stderr)
        self.assertEqual(self.snapshot(legacy), before)
        self.assertIn(str(self.proj), (self.state_dir / 'projects').read_text())

    def test_launch_hint_can_be_followed_after_the_launch(self):
        # 起動が新 state を作った後でも、案内の mv -T を順に打てば旧が新の名前へ移る（入れ子にならない）。
        legacy = self.make_legacy_state()
        result = self.run_c3c('claude', str(self.proj))
        token = r'(?:\\.|[^\s\\])+'
        commands = re.findall(rf'mv -T -- {token} {token}', result.stderr)
        self.assertEqual(len(commands), 2, result.stderr)
        for command in commands:
            subprocess.run(['bash', '-c', command], check=True)
        self.assertFalse(os.path.lexists(legacy))
        self.assertEqual((self.state_dir / 'projects').read_text(), str(self.proj) + '\n')

    def test_check_without_ledger_points_to_legacy_ledger_without_reading_it(self):
        legacy = self.make_legacy_state()
        before = self.snapshot(self.home)
        result = self.run_c3c('--check')
        self.assertIn('[WARN] 旧 state', result.stdout)
        self.assertIn('旧 state に起動台帳があります', result.stdout)
        self.assertNotIn(f'=== {self.proj} ===', result.stdout)
        self.assertEqual(self.snapshot(self.home), before)

    def test_clean_all_leaves_legacy_state(self):
        legacy = self.make_legacy_state()
        (legacy / 'mcp-approvals').mkdir()
        self.state_dir.mkdir(parents=True)
        before = self.snapshot(legacy)
        result = self.run_c3c('--clean')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.snapshot(legacy), before)

    def test_clean_project_leaves_legacy_state(self):
        legacy = self.make_legacy_state()
        before = self.snapshot(legacy)
        result = self.run_c3c('--clean', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.snapshot(legacy), before)
```

`test-build.sh:835` を置き換える:

```bash
  check "旧 state の検出と案内（読まない・移さない・消さない、mv -T の案内）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_legacy_state.py"
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_legacy_state.py' -v; PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_c3c_launch.py' -k LegacyState -v`
Expected: `resolve_state_dir` の抽出は成功するが、S2-2・S2-2b・S2-3（旧が移る、または `mv -T` の案内が無い）、S2-4 と `QuotedHomeTests` の同じもの、launch 側の 5 件が FAIL（`test_c3c_launch.py` の import に `re`・`subprocess` が無ければ足す）。

- [ ] **Step 3: 実装する**

`c3c` の `# 上書きしない rename（renameat2 ...` から `readonly CC_STATE_DIR CC_LEGACY_STATE_DIR CC_STATE_NOTICE CC_LEDGER_FILE` の直前まで（`rename_noreplace()` と `resolve_state_dir()`）を次に置き換える:

```bash
# state directory（起動台帳・MCP/Codex/project 設定の承認記録・CLI 選択の記憶）は ~/.local/state/c3c。
# 旧名 ~/.local/state/claude-container は v16 で自動移行と読み取りを廃止した（改名 第 2 段）。旧が残っていれば
# 検出して案内するだけで、中身は読まない・移さない・消さない（移さずに進めると承認の確認がもう一度出る＝
# 確認の側に倒れる）。案内の mv は -T 付き（新が既にあるとき旧を新の中へ入れずに失敗させる）で、パスは %q で
# クォートする（$HOME に ' や空白を含んでもそのまま打てる）。判定は lstat（symlink を辿らない）。
# $HOME から直接算出して readonly にし、プロジェクト側 env からの上書きを封じる（#39）。
# ここは関数定義セクションより前なので guard_warn は使えない（stderr へ直接出す）。
resolve_state_dir() {
  local new="$HOME/.local/state/c3c" old="$HOME/.local/state/claude-container" q_old q_new
  CC_STATE_DIR="$new"
  CC_LEGACY_STATE_DIR="$old"
  CC_STATE_NOTICE=""
  [[ -e "$old" || -L "$old" ]] || return 0
  printf -v q_old '%q' "$old"
  printf -v q_new '%q' "$new"
  if [[ ! -e "$new" && ! -L "$new" && $CHECK -eq 1 ]]; then
    # --check は何も書かないので、新が無いまま。そのまま移せる。
    CC_STATE_NOTICE="旧 state $old が残っています（c3c v16 は読みません）。引き継ぐ場合は、c3c のセッションがすべて終わってから mv -T -- $q_old $q_new で移してください。移さずに起動すると、MCP 等の承認の確認がもう一度出て、起動台帳と CLI の記憶は空から始まります（README「旧名 claude-container からの移行（v16）」節）。"
  elif [[ ! -e "$new" && ! -L "$new" ]]; then
    # 通常起動は、この後の起動台帳の記録（record_project_in_ledger）で新を作る。案内は「新を退避してから移す」順にする
    # （新が空でないと mv -T は失敗する。入れ子にはならない）。
    CC_STATE_NOTICE="旧 state $old が残っています（c3c v16 は読まず、この起動で $new を新しく作ります）。旧の承認記録・起動台帳・CLI の記憶を引き継ぐ場合は、c3c のセッションがすべて終わってから mv -T -- $q_new $q_new.v16-new で新を退避し、mv -T -- $q_old $q_new で移してください（README「旧名 claude-container からの移行（v16）」節）。"
  elif [[ ! -d "$new" ]]; then
    CC_STATE_NOTICE="旧 state $old が残っています（c3c v16 は読みません）。新 state $new はディレクトリではない（壊れた symlink 等）ため使えません。$new を直すか取り除いてから、旧を引き継ぐ場合は mv -T -- $q_old $q_new で移してください。"
  else
    CC_STATE_NOTICE="旧 state $old が残っています（c3c v16 は読まず、$new を使います）。旧の承認記録・起動台帳・CLI の記憶が不要なら、中身を確かめて削除してください。引き継ぐ場合は、c3c のセッションがすべて終わってから mv -T -- $q_new $q_new.v16-new で新を退避し、mv -T -- $q_old $q_new で移してください。"
  fi
  if [[ $CHECK -ne 1 ]]; then
    echo "WARNING: $CC_STATE_NOTICE" >&2
  fi
  return 0
}
resolve_state_dir
CC_LEDGER_FILE="$CC_STATE_DIR/projects"
```

（最後の 2 行は現行の `resolve_state_dir` の呼び出しと `CC_LEDGER_FILE` の代入で、置換範囲に含まれるので必ず残す。その直後の `readonly CC_STATE_DIR CC_LEGACY_STATE_DIR CC_STATE_NOTICE CC_LEDGER_FILE` は置換範囲の外で、そのまま。）

（4 つの案内文はどれも「`mv -T -- $q_old $q_new で移して`」を含み、新が既にある（または作られる）場合はその前に「`mv -T -- $q_new $q_new.v16-new で新を退避し`」を含む。Step 1 の `mv_commands` と `LegacyStateLaunchTests` はこの形を前提にしているので、文言を変えるときは揃える。）

`clean_all()` から旧 state の分岐（`legacy_store` の宣言と `# 旧 state（改名 第 1 段）...` の if ブロック）を削除する:

```bash
  local approval_store="$CC_STATE_DIR/mcp-approvals"
  echo "MCP 承認記録を削除します: $approval_store"
  rm -rf "$approval_store" && echo "削除しました。" || echo "見つからないのでスキップします。"
  echo "起動台帳を削除します: $CC_LEDGER_FILE"
  rm -f "$CC_LEDGER_FILE" && echo "削除しました。" || echo "見つからないのでスキップします。"
```

同じ関数の先頭コメント「レガシー共有イメージ localhost/claude-container_claude-auth-workspace もこのパターンに自然にマッチするため、移行用の特別処理は不要。」は、spec の範囲外の節で整理してよいとされたので「旧製品名の共有イメージ（`localhost/<旧名>_claude-auth-workspace`）も同じパターンで拾う。」にする（旧名の文字列を識別子として持たないため）。

`run_check_mode()` の「起動台帳が空です」の分岐を次にする:

```bash
    if [[ ! -s "$CC_LEDGER_FILE" ]]; then
      echo "起動台帳が空です（$CC_LEDGER_FILE）。まだ通常起動が記録されていません。--check <directory> で個別指定できます。"
      # 第 1 段を経ずに v16 へ上げた利用者は、台帳が旧 state 側にしかない。旧は読まず、移してから再実行する
      # 2 段の手順を案内する（改名 第 2 段。案内の mv は上の [WARN] の文にある）。
      if [[ -s "$CC_LEGACY_STATE_DIR/projects" ]]; then
        echo "[WARN] 旧 state に起動台帳があります（$CC_LEGACY_STATE_DIR/projects）。上の案内に従って旧 state を移してから、c3c --check を再実行してください。"
      fi
    else
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_legacy_state.py' -v && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_c3c_launch.py' && ./test-build.sh --launcher-only && ./lint.sh`
Expected: すべて PASS。`lint.sh` は終了コード 0・警告ゼロ。

README.md「変更後の確認」節の state の段落（「state directory の移行（`c3c` の `resolve_state_dir()`・`rename_noreplace()`）の変更も …」）を次にする:

```markdown
旧 state の検出と案内（`c3c` の `resolve_state_dir()`、`run_check_mode()` の旧台帳の案内）の変更も `--launcher-only` に含む。単独では `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_legacy_state.py -v` を使う（旧を読まない・移さない・消さないこと、新の有無と型ごとの案内、`'` を含む HOME でも案内の `mv -T` をそのまま打てること。launcher 経由は `test_c3c_launch.py` の `LegacyStateLaunchTests`）。
```

- [ ] **Step 5: コミット**

```bash
git rm tests/test_state_migration.py
git add c3c tests/test_legacy_state.py tests/test_c3c_launch.py test-build.sh README.md
git commit -m "feat!: state の自動移行を削除し、旧 state は検出と案内だけにする"
```

---

### Task 7: 文書を v16 に合わせる

**Files:**
- Modify: `README.md`（「旧名 claude-container の識別子からの移行」節 298-318 行 → 「旧名 claude-container からの移行（v16）」、「旧 `.claude-container.d/` からの移行」節 270-296 行の統合、156・169 行、「変更後の確認」節の `.claude-container.d` fixture の記述 766 行）
- Modify: `docs/development-invariants.md`（7・24・26・31・35・50・52・57-60・70・110・126 行）
- Modify: root `AGENTS.md`（7・26 行）
- Modify: `examples/c3c/env.example:3`、`docs/sandbox-considerations.md:9`

**Interfaces:**
- Consumes: Task 1〜6 の挙動（案内文が参照する節名「旧名 claude-container からの移行（v16）」はこの Task で作る）。

- [ ] **Step 1: README の移行節を書き直す**

「旧名 claude-container の識別子からの移行」節（見出しから「旧版へ戻したとき」の段落まで）と「旧 `.claude-container.d/` からの移行」節を、次の 1 節にまとめる（見出しの位置は現在の「旧 `.claude-container.d/` からの移行」節の位置。「旧コマンドからの移行」節は範囲外なので残す）:

```markdown
### 旧名 claude-container からの移行（v16）

v16 で、旧製品名 `claude-container` を含む識別子の互換読み取りを削除した（v15.1 系では `WARNING` 付きで読めた）。旧名が残っていると、次のとおり起動が止まるか、案内が出る。`c3c --check` で 4 種をまとめて確かめられる。

| 対象 | 旧名 | 新名 | v16 での扱い |
|---|---|---|---|
| env キー（`.c3c/env`・シェル環境） | `CLAUDE_CONTAINER_NO_FIREWALL`・`CLAUDE_CONTAINER_IPV6` | `C3C_NO_FIREWALL`・`C3C_IPV6` | 空でない値があれば `ERROR`（`--check` は `[FAIL]`） |
| 設定ディレクトリ | `.claude-container.d/` | `.c3c/` | 存在すれば `ERROR`（`.c3c/` の有無を問わない） |
| state directory | `~/.local/state/claude-container/` | `~/.local/state/c3c/` | 読まない。残っていれば `WARNING`（`--check` は `[WARN]`） |
| イメージ | label `claude-container.*`、コンテナ内の `/etc/claude-container/*`・`~/.config/claude-container/secrets` | label `io.c3c.*`、`/etc/c3c/*`・`~/.config/c3c/secrets` | v15 以前にビルドしたイメージは `ERROR` で `-b` を案内（`--check` は `[FAIL]`）。由来 label を旧名でだけ持つ v15.0 以前のプロジェクトイメージは `--check` で `[WARN]`（自動清掃しない） |

移行の手順（c3c のセッションをすべて終えてから行う）:

1. **v16 へ上げる前に**（v15.1 系のうちに）`c3c --check --clean-missing` で、削除済みのプロジェクトのイメージを清掃する。v16 は旧 label を読まないので、v15.0 以前のイメージは自動清掃の対象から外れる（`--check` が ID と削除の手順を示す）。
2. **env キー**: `.c3c/env` とシェルの起動ファイル（`export CLAUDE_CONTAINER_...`）の両方を確かめ、新キーに書き換える。
3. **設定ディレクトリ**: プロジェクト直下で `mv -T -- .claude-container.d .c3c`（Git 追跡対象なら `git mv`）。`.gitignore` の `.claude-container.d/env` は `.c3c/env` に書き換える。`.c3c/` が既にある場合は、中身を確かめてから旧名をプロジェクトの外へ退避する。
4. **state directory**: v15.1 系で一度でも通常起動していれば、自動で移っている。旧が残っているときは、先に `c3c --check` を実行すると、そのまま打てる `mv -T -- <旧> <新>` が案内に出る（`--check` は何も書かないので新はまだ無い）。v16 で通常起動した後は新が作られているので、案内に従って新を退避（`mv -T -- <新> <新>.v16-new`）してから旧を移す。旧が不要なら、中身を確かめて削除する。移さずに起動すると、MCP 等の承認の確認がもう一度出て、起動台帳と CLI の記憶は空から始まる。`mv -T` は旧を新の中へ入れ子にしない（新が空でなければ失敗する）。
5. **イメージ**: 各プロジェクトを `-b` で再ビルドする（`c3c claude -b <dir>` / `c3c codex -b <dir>`）。
6. **秘密のパス**: 自分のスクリプトや MCP 設定がコンテナ内の `~/.config/claude-container/secrets` を読んでいれば、`~/.config/c3c/secrets` に直す（v15.1 系は両方に載せていた。v16 は新パスだけ）。
7. `c3c --check` で `[FAIL]` と旧名の `[WARN]` が無いことを確かめる。

**v15.1 系へ戻したとき**:

- v15.1 系は新名（`C3C_*`・`.c3c/`・`~/.local/state/c3c/`・`io.c3c.*`）を読むので、移行後の設定はそのまま使える。
- v15.0 以前へ戻す場合: `.c3c/env` に書いた `C3C_*` は「解釈しない」`WARNING` 付きで無視され、シェル環境だけで渡した `C3C_*` は何も出さずに無視される。どちらもファイアウォールの無効化と IPv6 は効かない（有効・IPv4 のまま＝安全側）。v15.0 以前は旧 state だけを読むので、承認の確認がもう一度出て起動台帳は空になる。v16 のイメージは旧 label を持たないので、ドリフトの「ハッシュラベルがありません」`WARNING` が出て、`C3C_IPV6` 相当の IPv6 は対応確認で拒否される（戻した版で `-b` すれば解消）。この項は実装時に `git show v15.0.0:c3c` で該当箇所（state のパス、`guard_asset_drift`・`guard_ipv6` の label 名）を確かめてから書く。
- v16 でビルドしたイメージを v15.1 系の c3c で起動すると、承認記録が新しいパス（`/etc/c3c/*`）に載らないため、MCP と project 設定の確認がもう一度出る。Codex は起動時 MCP 審査の再照合で止まる（いずれも安全側）。戻した版で `-b` すれば解消する。
```

156 行の「v15.1 系では旧名 `claude-container.project-*` も同じ値で併記する…」は「v15.1 系は旧名 `claude-container.project-*` も併記していた。v16 は旧名を読まず、旧 label だけのイメージは清掃の対象外として `[WARN]` で示す」にする。169 行の検査項目の「`.c3c/` と旧 `.claude-container.d/` の有無・型・二重配置」は「`.c3c/` の有無・型と、旧名 `.claude-container.d/` の残存」にし、「旧 env キー・旧 state・旧 label だけのイメージ・イメージの配置 label」を検査項目に足す（Task 1 で足した項目と重複させない）。766 行の「旧設定名 `.claude-container.d/` の fixture は互換読込の検査として残す」は「旧設定名 `.claude-container.d/` は、存在すると起動を止める検査の fixture としてだけ使う」にする。

`docs/development-invariants.md` の 85 行（Codex 経路の順序の説明にある承認記録のパス）も `/etc/c3c/` にする（Task 2 の grep で直っていれば確認だけ）。

`grep -n -E 'claude-container|CLAUDE_CONTAINER|移行期間|第 2 段|次のメジャー版' README.md` で残りを洗い、範囲外（帰属表示 3 行、公開リポジトリの旧名 44 行、旧コマンドの節 54・102・110-132 行、LICENSE の 819 行）と上の移行節を除いて、v16 の挙動に合わせる。

- [ ] **Step 2: 開発者向け文書を直す**

`docs/development-invariants.md`:
- 7 行: 「（`.c3c/env`、旧名 `.claude-container.d/env`。…）」→「（`.c3c/env`。…）」。
- 24 行（state directory の移行）: 次に置き換える。「state directory（`resolve_state_dir()`、改名 第 2 段）: `CC_STATE_DIR` は常に `~/.local/state/c3c`。旧 `~/.local/state/claude-container` は検出して案内するだけで、読まない・移さない・消さない（`--clean` も消さない）。案内の `mv` は `-T` 付き・パスは `printf %q`（新が既にあるとき旧を新の中へ入れない）。判定は lstat。`--check` は旧台帳の存在だけを見て移行後の再実行を案内し、中身を読まない。」
- 26 行: 起動台帳のパスの「改名 第 1 段で旧 state を使い続ける環境では …」を削除する。
- 31 行: 「ラベル `io.c3c.base-image`（空なら旧名 `claude-container.base-image`。`image_label()`）」→「ラベル `io.c3c.base-image`（`image_label()`。旧名は読まない）」。
- 35 行（設定ディレクトリの選択）: 旧名は存在すれば `guard_fail`（型・`.c3c` の有無を問わない、`-e` と `-L` で判定）に書き換え、「新旧配置で同じ入力なら同じ hash・同じ staging になる契約」を削除する。
- 50・57・58 行: マウント先を `/etc/c3c/...` にする。
- 52 行: 由来 label は `io.c3c.project-*` だけを書き・読む。旧 label だけのイメージは `project-images.py` の `legacy_only()` で検出して `[WARN]`、削除候補にしない（旧 label の値を由来判定に使わない）。
- 59 行: 秘密は `/home/node/.config/c3c/secrets` だけに `:ro` でマウント（`lint.sh` が `:ro` と旧パスの不在を検査）。
- 60 行: env キーは `C3C_NO_FIREWALL`・`C3C_IPV6` だけ。旧キーは `guard_legacy_env_keys()` が `.c3c/env` の行とシェル環境の両方で拒否する。`entrypoint.sh` は旧キーを読まない（渡っても無効化しない＝安全側）。`lint.sh` の C-1 が旧キーの不在を検査。
- 70 行: 「（旧名 `claude-container.asset-hash` も同じ LABEL 命令に併記。`#30`）」を削除し、`LABEL io.c3c.image-layout`（`guard_image_layout()` が照合）も同じ位置に置くことを足す。
- 新しい項目: 「`guard_image_layout()`（改名 第 2 段）: 既存イメージの `io.c3c.image-layout` が `IMAGE_LAYOUT_VERSION` と一致しなければ `guard_fail`。通常起動ではガード列（`guard_asset_drift` の後。ホストの MCP 承認の対話・検査用コンテナ・本起動より前）で呼び、`-b` のときは見ない（この後に作り直すため）。`--check` ではイメージがあるときに呼ぶ。未ビルドなら何もしない。コンテナ内のパスや env の配置を変えたら値を上げる。」
- 110・126 行: 旧 `.claude-container.d/` の記述を外す。

root `AGENTS.md` 7 行の「（旧名 `.claude-container.d/` も移行期間中は読める）」と 26 行の「（旧 `.claude-container.d/`）」を削除する。`examples/c3c/env.example:3` の「（旧名 .claude-container.d/env も移行期間中は読める。両方は…）」を削除し、文が続くように整える。`docs/sandbox-considerations.md:9` の `.claude-container.d/` を `.c3c/` にする。

- [ ] **Step 3: 旧名の残りを確かめる**

Run: `git ls-files | grep -v -E '^docs/superpowers/(plans|specs)/' | xargs grep -n -E 'claude-container|CLAUDE_CONTAINER' | grep -v -E '^(LICENSE|README.md):'`
Expected: 残るのは、`c3c` の検出と案内（`PROJECT_CONF_LEGACY_NAME`、`resolve_state_dir()` の旧パス、`guard_legacy_env_keys()` の旧キー、旧入口の案内 6・77 行）、`project-images.py` の `LEGACY_LABEL_PREFIX`、`lint.sh` の否定検査、テストの fixture と否定検査、`AGENTS.md` の upstream の帰属表示、`docs/development-invariants.md` の「旧名は読まない」類の説明だけ。それ以外が出たら直す。README.md は Step 1 の `grep` で確かめ済み。

Run: `./lint.sh && ./test-build.sh --launcher-only`
Expected: PASS（E7 を含む）。

公開リポジトリの外（ops リポジトリの `.claude/AGENTS.md` と `release-tag` skill の「`.c3c/`（旧 `.claude-container.d/`）」の記述）は、この PR の範囲外。PR のマージ後に ops リポジトリへ別コミットで追随する（`git -C .claude ...`。ops への定型コミットは作業の区切りでまとめてよい）。

- [ ] **Step 4: コミット**

```bash
git add README.md docs/development-invariants.md AGENTS.md examples/c3c/env.example docs/sandbox-considerations.md
git commit -m "docs: 旧名 claude-container からの移行（v16）を 1 節にまとめ、開発文書を第 2 段に合わせる"
```

---

### Task 8: 全体の検証（実機を含む）

**Files:**
- Modify: この計画ファイル（末尾に「実機確認の記録」節を足す）

- [ ] **Step 1: 自動テストの全体**

Run: `./lint.sh && ./test-build.sh --validator-only && ./test-build.sh --launcher-only && bash examples/hooks/tests/test-block-pr-approve.sh`
Expected: すべて PASS。`lint.sh` は終了コード 0・警告ゼロ。

ホスト（実 Podman あり）で: `TMPDIR=/tmp ./test-build.sh`（全体。実イメージのビルドと `io.c3c.image-layout`・`/etc/c3c/*` の確認を含む）と `./test-build.sh --config-ro-only`。コンテナ内では実 Podman が無いので `not run` と理由を記録する。

- [ ] **Step 2: 実機で `--check` の 4 種の検出を確かめる（タグ提案の前提、root `AGENTS.md`）**

ホストで、使い捨ての fixture プロジェクト（`mktemp -d` 配下）と、v15.1.0 の checkout（`git worktree add --detach <path> v15.1.0`）を使う。持ち主の実 state を触る前に `cp -a ~/.local/state/c3c <退避先>` で退避する（実 state に旧 state を作る手順は、退避した上で使い捨ての `HOME` を使ってもよい。その場合は `HOME` を変えた旨を記録する）。

1. v15.1.0 の c3c で fixture を `-b` でビルドする（旧イメージ: `io.c3c.image-layout` なし）。
2. fixture に `.claude-container.d/`（`.c3c` とは別）を置き、`HOME` の `.local/state/claude-container/projects` に fixture のパスを書き、シェル環境で `CLAUDE_CONTAINER_IPV6=0` を export する。
3. v16 の c3c で `c3c --check <fixture>` を実行し、出力を記録する。
   Expected: 旧設定ディレクトリ `[FAIL]` と旧 state `[WARN]` が出る（旧設定ディレクトリの FAIL で、その対象の env・ガード・イメージの診断は止まる）。
4. `.claude-container.d` をプロジェクトの外へ退避して再実行する。
   Expected: 旧 env キー `[FAIL]`・イメージの配置 `[FAIL]`・旧 state `[WARN]` が出る。
5. 旧 label だけのイメージ: v15.0.0 の checkout でビルドしたイメージ（または `podman image inspect` で旧 label だけを持つことを確かめたイメージ）について、`c3c --check --clean-missing` が削除せず `[WARN]` で ID と手順を出すこと。v15.0.0 のビルドが重い場合は、`podman build` で `LABEL claude-container.project-metadata=1 claude-container.project-path=<fixture> claude-container.project-name=<key>` を持つ最小イメージを `localhost/<key>_claude-auth-workspace` の名前で作って代える（代えたことを記録する）。

- [ ] **Step 3: 実機で `-b` 後の全経路を確かめる**

v16 の c3c で、旧名を取り除いた fixture（または持ち主の利用側プロジェクト 1 つ）について:

1. `-b` なしの通常起動が `io.c3c.image-layout` の `ERROR` で止まり、compose を呼ばないこと。
2. `c3c claude -b <dir>` で起動し、コンテナ内で `ls /etc/c3c/`（許可ドメイン・ポート・GitHub meta・承認記録 3 本）、`ls /home/node/.config/c3c/secrets`（`SECRETS_DIR` があれば）、`test ! -e /etc/claude-container && test ! -e /home/node/.config/claude-container` を確かめる。`git push --dry-run` 相当で askpass が新パスの `GITHUB_MAIN_PAT` を読むこと（配線がある場合）。
3. `.mcp.json` に stdio サーバーがあるプロジェクトで、承認済みなら確認が出ずに起動し、承認記録を消すと確認が出ること。
4. `c3c codex <dir>` で preflight・承認・本起動が通ること。
5. `.c3c/env` に `C3C_IPV6=1` を書いて起動し、IPv6 の override が効くこと（`podman inspect` の network mode）。`C3C_NO_FIREWALL=1` で起動時の WARNING と無制限の通信。
6. ロールバック: v15.1.0 の c3c で v16 のイメージを起動し、MCP・project 設定の確認がもう一度出ること、Codex が verify で止まること（README の記述どおり）。

- [ ] **Step 4: 記録とコミット**

この計画ファイルの末尾に「## 実機確認の記録（Task 8、<日付>、<ホスト/コンテナ>、実装 <commit>）」節を足し、Step 1〜3 の各項目の結果（コマンドの抜粋、PASS/FAIL、`not run` と理由）を事実だけ書く。

```bash
git add docs/superpowers/plans/2026-09-29-rename-legacy-identifiers-stage2.md
git commit -m "docs: 改名 第 2 段の実機確認の結果を計画に記録する"
```

- [ ] **Step 5: タグの提案（実装者は作らない）**

MAJOR（v16.0.0）。根拠: `.c3c/` 以外の設定ディレクトリ名・env キー・state の読み取りを削除し、v15 以前のイメージは `-b` なしでは起動しない（利用者が対応しないと従来どおり動かない）。タグ本文には、移行節の表と手順、`--check` の 4 種、v15.1 系へ戻したときの挙動を載せる。提案は持ち主の承認後に `release-tag` skill で作成する。

---

## 計画レビューの記録

- 1 巡目（未コミットの計画、2026-09-29）: Codex（gpt-6-astra、`codex exec --sandbox read-only`）は「修正後に渡せる」、Critical 1・Important 4・Minor 3。Claude（claude-opus-5-5、headless `claude -p` 読み取り専用。`modelUsage` で確認）は「修正後に渡せる」、Critical 0・Important 3・Minor 9。反映した主なもの:
  - Codex C1: Task 6 の置換範囲で `resolve_state_dir` の呼び出しと `CC_LEDGER_FILE` が消える。
  - Codex I1: Task 1 のイメージがパスの変更前に `image-layout=2` を持つ。label を Task 2 へ移した。
  - 両者の I（Codex I2・Claude I-3）: 検査がコメントの旧名に当たる。コメントに旧名を綴らない規則にし、正規表現を Task ごとに広げる形にした。
  - 両者（Codex I3・Claude M-3）: 旧 label のイメージの案内のクォート。
  - Codex I4: 対象を指定した診断で、台帳に無い旧 label のイメージが出ない。
  - Claude I-1: 通常起動の案内が、起動自身が新 state を作るので実行できない。
  - Claude I-2: `legacy_only` が中間イメージを巻き込む。定義を由来 label と値・名前で絞った。
  - Minor: 全件を反映した。Claude M-7 はゲートをガード列へ前倒しした。M-8 は ops への追随を Task 7 に 1 行足した。M-9 の v15.0 の挙動は、実装時に `git show v15.0.0:c3c` で確かめてから書く指示にした。
- 確認限定巡 1 回目: Claude（`--resume`、claude-opus-5-5）は I-1〜I-3 がすべて「直った」、判定「実装に渡せる」。Codex（gpt-6-astra、前回の全文を渡した新しい read-only セッション）は C1・I2「直った」、I1・I3・I4「一部」、判定「修正後に渡せる」。新たな矛盾 1 件（Task 1 の冒頭の `-b` の記述）を指摘。途中の版のイメージの扱いの明記、引用符・特殊文字のパスのテスト（P2-1b）、対象指定時の名前なしの旧版イメージの表示（P2-5b）、Task 1 の冒頭の文言を反映した。
- 確認限定巡 2 回目（Codex のみ、gpt-6-astra）: I1・I3・I4 と Task 1 冒頭の矛盾がすべて「直った」、判定「実装に渡せる」。両レビュアーとも「実装に渡せる」で収束（計 3 巡、うち Claude 2 回・Codex 3 回の呼び出し）。

区分: 境界（ファイアウォールを無効化する env キー、MCP・Codex・project 設定の承認記録のマウント先、秘密のマウント先と askpass の読み先を変え、`docs/development-invariants.md` の不変条件を書き換えるため）
推奨実装: Opus（秘密の読み先と承認記録の経路という境界に触れ、Task 1 のゲートの配置や Task 5・6 のテスト書き換えで実装中の判断が残る。Codex は host の checkout で完結する点では候補だが、Task 5 の `test_c3c_config.py` の書き換えが方針指示に留まり逐語手順まで確定していないため推さない。Sonnet は境界変更のため推さない）
実装: Opus（持ち主指定 2026-09-29。推奨の提示に「続けて」と回答）

## 実機確認の記録（Task 8、2026-09-29、コンテナ内、実装 0363775）

- Step 1（コンテナ内で実行）: `./lint.sh` rc 0・警告ゼロ（Compose の検証は podman が無いため not run）。`./test-build.sh --launcher-only` PASS=448・FAIL=0。`./test-build.sh --validator-only` PASS=82・FAIL=0。`bash examples/hooks/tests/test-block-pr-approve.sh` 全ケース green。`python3 -m unittest discover -s tests -p 'test_*.py'` 445 件 OK（skip 12 件は `test_codex_entrypoint.py` の ComposeContractTests で、podman が無いため。変更前と同数）。
- Step 1 のうち `TMPDIR=/tmp ./test-build.sh`（全体。実イメージのビルドと `io.c3c.image-layout`・`/etc/c3c/*` の確認）と `--config-ro-only`: not run（コンテナ内に実 Podman が無い。ホストで実施する）。
- Step 2・3（`--check` の 4 種の検出、`-b` 後の全経路、ロールバック）: not run（ホストが必要）。
