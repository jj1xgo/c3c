# A. 公開計画: Claude 起動既定を `--permission-mode auto` にする（c3c）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

保存先: `docs/superpowers/plans/2026-09-21-c3c-auto-permission-mode.md`。基点は main `6150cc5`。

## Context

c3c の Claude 経路は `entrypoint.sh` の末尾（`CC_AGENT=claude` の分岐内）で `claude --dangerously-skip-permissions` を exec している。全利用者の Claude 起動既定を Claude Code の auto mode（`--permission-mode auto`）へ変えることは承認済み。試行ブランチ `trial/auto-permission-mode` は同じ行を差し替えただけだが main より古く、現行 main は Codex 経路（`codex-mcp-audit.py` の verify → 固定 argv exec）を同じファイルで維持している。試行ブランチは merge せず、main 起点の新ブランチで同じ 1 行の変更を再適用する。

Claude Code 公式の permission modes の説明（https://code.claude.com/docs/en/permission-modes 、2026-09-21 に確認）によれば、`--permission-mode auto` を指定しても auto が利用できないセッション（unsupported model、settings の `disableAutoMode`、サーバー側で無効等）では Claude Code 本体が Manual に戻る。したがって起動結果は 2 種類を区別する。

- **引数を受理しない古い版**: `claude` が非ゼロで終了し、コンテナも launcher もそのまま失敗する。
- **引数を受理するが auto が利用できないセッション**: Claude Code 本体が Manual にし、ツール使用ごとの確認プロンプトが出る。起動自体は成功する。

どちらの場合も c3c は `--dangerously-skip-permissions` で再試行しない。`claude --help` に `--permission-mode` や `auto` の文字列があることは「引数を受理する」ことの根拠にしかならず、auto mode が実際に有効かどうかはセッション内の表示で実測する。

設計上の固定事項（実装で崩さない）:

- **bypass へ戻さない。** fallback 分岐、`.c3c/env` や secrets 経由の切替は設けない（bypass は auto より緩い側なので、切替可能にすると境界の緩和経路になる）。
- **コンテナ境界は変えない。** firewall・capability 剥奪・`:ro` マウント・秘密の非 export はそのまま。auto mode と Manual の判定はいずれも Claude Code 本体の機能であり、claude-container はこれを境界に数えない。
- **MCP 事前審査は維持する。** `entrypoint.sh:87-140` の stdio ゲート（TOFU 照合＋TTY 確認、opt-out なし）と Codex 経路の snapshot/verify は変更しない。このゲートは Claude Code 側の承認プロンプトに依存しない設計なので、auto でも Manual でも意味は変わらない。
- **未計測の挙動を事実として書かない。** README に書けるのは「引数が固定であること」「判定を境界に数えないこと」「公式文書が述べる Manual への戻り」「従来の既定下での過去の実測」まで。auto mode 下で Claude Code 側の MCP 承認プロンプトがどう振る舞うかは未計測と明記する。
- **過去記録を改変しない。** `docs/superpowers/plans/*`・`docs/superpowers/specs/*`（`2026-09-20-c3c-incremental-design.md:44` の「末尾は `exec claude --dangerously-skip-permissions`」を含む）、既存 tag と Release 本文、vault の handover・知見ノートは当時の記録として残す。
- **版番号を断定しない。** 文書では「従来の既定」「現在の既定」と書き、次版番号や「vX まで」の表現を使わない。

## 開始時の手順（他セッション保護）

1. `git status`・`git branch --show-current`・`git worktree list` で現在の branch・差分・worktree を確認する。共有 checkout の main では `git switch` しない。
2. 既存 worktree と同じ置き場（`git worktree list` の結果に従う）に `c3c/auto-permission-mode` 用の専用 worktree を main `6150cc5` から追加し、その中で実装する。
3. 計画ファイルの保存だけ（製品未変更）は現在の checkout の `docs/superpowers/plans/` に置いてよい。
4. 基準値: 変更前の main `6150cc5` で `tests/test_codex_entrypoint.py` の 15 テストは host で成功している。Podman の `/run/user/<uid>/libpod` が読めない sandbox 内では `ComposeContractTests` の 9 subtest が環境制約で失敗するため、検証は Podman を使える host で行う。この基準値は変更後の結果ではない。

## 変更ファイル

| ファイル | 変更 |
|---|---|
| `entrypoint.sh` | `exec claude --dangerously-skip-permissions`（212 行目）を `exec claude --permission-mode auto` に変え、再試行しない旨のコメントを添える |
| `tests/test_codex_entrypoint.py` | 145 行目の期待 argv を更新する（それ以外は変えない） |
| `docs/development-invariants.md` | `entrypoint.sh` 項に「起動引数固定・再試行なし」の不変条件を追加、108 行目の前提文を更新 |
| `README.md` | 497・603・405・615 行目の現状記述を更新し、旧イメージ・版固定・Manual への戻りの帰結と「変更後の確認」の追加検証を書く |
| `AGENTS.md` | 11 行目のミッション文（`--dangerously-skip-permissions` を明記）を実装と整合させる |

`compose.yml`・`Dockerfile.claude`・`claude-container`・`codex-mcp-audit.py`・`test-build.sh`・Codex 経路のテストは変更しない。`entrypoint.sh` は `ASSET_HASH_TARGETS`（`claude-container:1984-2006`）に既に含まれるため launcher 側の追加登録は不要。`tests/runtime-probe.py:23` は引数の個数と `--control-` 接頭辞だけを見るので、`tests/test-runtime.sh` の protected 段階は引数変更で壊れない（実装者は同ファイルを読んで再確認する）。

## Task 1: 受理可否の計測（実装より先）

1. `./test-build.sh --build-only`（host）で `localhost/claude-test` を最新 Claude Code でビルドする。Expected: `[OK] podman build --no-cache`、`[OK] claude --version`、終了コード 0。
2. `podman run --rm localhost/claude-test claude --help | grep -n -- '--permission-mode'` の出力全文を結果ファイル（`docs/superpowers/plans/2026-09-21-c3c-auto-permission-mode-results.md`）へ転記する。これは「引数を受理する版か」の参考情報で、auto が有効かの判定には使わない。
3. `--permission-mode` が無い、または受理値に `auto` が無い場合は **ここで止めて報告する**（fallback を書かない。対応版の固定案は持ち主判断）。

## Task 2: `entrypoint.sh`

`entrypoint.sh:211-213` を次に置き換える。Codex 経路（215 行目以降）は無変更。

```bash
if [ "$CC_AGENT" = claude ]; then
  # Claude 経路の起動引数は固定（Claude Code の auto mode）。引数を受理しない版ではそのまま非ゼロで
  # 終了し、auto が利用できないセッションでは Claude Code 本体が Manual に戻す（公式 permission-modes
  # 文書）。いずれの場合も旧既定の --dangerously-skip-permissions で再試行しない（env による切替も
  # 設けない）。auto / Manual の判定は Claude Code 本体の機能で、この container の境界には数えない
  # （README「セキュリティモデル」節）。
  exec claude --permission-mode auto
fi
```

## Task 3: `tests/test_codex_entrypoint.py`

145 行目のみ変更する。

```python
                self.assertEqual(self.records[2], 'claude --permission-mode auto')
```

追加テストは設けない。`test_default_and_explicit_claude_keep_existing_order_and_argv` は記録が `['sudo', 'refresh', 'claude', 'claude-env']` であることを既に検証しており、`claude` の呼び出しが固定 argv でちょうど 1 回であることを含む。`exec` はプロセスを置き換えるため再試行は構造上起きず、fake claude の非ゼロ終了を足しても実装をなぞる検査にしかならない。ソース全文に対する文字列検査も設けない（Task 2 のコメントが旧フラグ名を含むため）。

## Task 4: `docs/development-invariants.md`

- `entrypoint.sh` 項（61-68 行目）に 1 項目追加: 「Claude 経路の起動引数は `claude --permission-mode auto` 固定（2026-09-21。従来の既定は `--dangerously-skip-permissions`）。引数を受理しない版では非ゼロ終了のままにし、auto が利用できないセッションで Claude Code 本体が Manual に戻す場合（公式 permission-modes 文書、2026-09-21 確認）も含め、旧フラグへ戻す分岐・env による切替を設けない（`tests/test_codex_entrypoint.py` が argv を検査）。auto / Manual の判定は Claude Code 本体の機能で、境界に数えない。」
- 108 行目冒頭「コンテナ内で Claude は `--dangerously-skip-permissions` で動作するため、ツール使用の確認プロンプトなしに動作する。」→「コンテナ内で Claude は `--permission-mode auto`（Claude Code の auto mode）で動作し、claude-container はツール使用ごとの人手の確認プロンプトを境界として当てにしない（auto が利用できないセッションでは Claude Code 本体が Manual に戻り確認プロンプトが出るが、境界の扱いは変わらない）。」以降は据え置き。

## Task 5: `README.md`

- 497 行目（アーキテクチャ・`entrypoint.sh`）: 「`claude --dangerously-skip-permissions` を起動する」→「`claude --permission-mode auto`（Claude Code の auto mode。引数を受理しない版では起動失敗のまま止め、auto が利用できないセッションでは Claude Code 本体が Manual に戻す。いずれも旧既定の `--dangerously-skip-permissions` で再試行しない）を起動する」。
- 603 行目（セキュリティモデル冒頭）: 「Claude は `--dangerously-skip-permissions` で起動するため、ツール使用の確認プロンプトなしに動作する。」→「Claude は `--permission-mode auto`（Claude Code の auto mode）で起動する。auto が利用できないセッション（unsupported model、settings の `disableAutoMode`、サーバー側で無効等）では Claude Code 本体が Manual に戻る（[公式 permission modes](https://code.claude.com/docs/en/permission-modes)、2026-09-21 確認）。auto / Manual の判定は Claude Code 本体の機能であり、claude-container はそれを境界に数えない。」以降「ガードレールはコンテナ境界 — …」は据え置き。同段落末尾に追加: 「既存のイメージは `-b` で再ビルドするまで旧 entrypoint（従来の既定 `--dangerously-skip-permissions`）のまま動く。起動時と `--check` の境界アセットのドリフト `WARNING` が再ビルドの合図になる（fail-open のため起動は止めない）。`CLAUDE_CODE_VERSION` で `--permission-mode auto` を受理しない版を固定している場合は起動が失敗し、旧フラグへは戻らない。」
- 405 行目: 「`--dangerously-skip-permissions` 下では Claude Code 本来の MCP 承認プロンプトも機能しないため（後述「セキュリティモデル」節）、この対話確認が唯一の壁になる。」→「Claude Code 本来の MCP 承認プロンプトは壁に数えない（従来の既定 `--dangerously-skip-permissions` 下で機能しないことを実機確認済み。auto mode 下は未計測。後述「セキュリティモデル」節）ため、この対話確認が唯一の壁になる。」
- 615 行目: 見出し太字「**MCP サーバーの承認プロンプトは機能しない**」→「**MCP サーバーの承認プロンプトを壁に数えない**」。本文「`--dangerously-skip-permissions` 下ではこの確認が実行されないことを実機で確認済み（…）」の「`--dangerously-skip-permissions`」の前に「従来の既定」を補い、直後に「現在の既定 `--permission-mode auto` 下の挙動は未計測で、いずれにせよ承認系の設定（`enabledMcpjsonServers` 等）はコンテナ内から書き換え可能なため壁にならない。」を挿入。残りは据え置き。
- 「変更後の確認」節（673 行目の段落の後）に追加: 「`entrypoint.sh` の Claude 起動引数（`--permission-mode auto`）を変更した場合は `tests/test_codex_entrypoint.py`（`--launcher-only` に含む）に加え、`-b` の再ビルドと実起動で `podman top <container> pid,args` に引数が出ること（実 argv）、セッション内の表示で permission mode を確認すること（実モード。auto が利用できないセッションでは Manual になる）、再ビルド前の旧イメージに対して起動時と `--check` がドリフトの `WARNING`／`[WARN]` を出すことを実 Podman で確認する。CLI 選択の記憶により `c3c -b` は Codex を起動しうるため、Claude の確認では `c3c claude` と明示する。」

## Task 6: `AGENTS.md`

11 行目を実装と整合させる: 「本リポジトリのミッションは「Claude Code を人手の確認プロンプトに頼らず走らせる（既定 `--permission-mode auto`、従来は `--dangerously-skip-permissions`）ための、プロジェクト非依存なサンドボックス境界の提供・維持」である。」通常の文言選択として行い、追加承認は求めない。

## 検証コマンドと Expected

| 段階 | コマンド | Expected |
|---|---|---|
| lint | `./lint.sh` | `lint OK`、終了コード 0、警告ゼロ |
| 単体 | `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_codex_entrypoint.py -v`（host） | 15 テスト `ok`。`test_default_and_explicit_claude_keep_existing_order_and_argv` が `claude --permission-mode auto` を確認 |
| launcher | `TMPDIR=/tmp ./test-build.sh --launcher-only` | 全 `[OK]`、`FAIL=0` |
| hook | `bash examples/hooks/tests/test-block-pr-approve.sh` | 全 `[OK]`（無影響の確認） |
| 旧イメージのドリフト（再ビルド前） | `./c3c claude --check <対象 dir>`（引数の並びは README「c3c 入口（CLI の選択と記憶）」節の書式に従う） | `[WARN] 境界アセット（entrypoint.sh・init-firewall.sh 等）がイメージのビルド後に変更されています。-b でのリビルドを推奨します。` |
| 再ビルドと Claude 実起動 | `./c3c claude -b <対象 dir>` | build が run と別ステップで成功し、`claude` が起動する。引数を受理しない版なら非ゼロで終了し再試行しない（この場合は止めて報告） |
| 実 argv | 起動中に別端末で `podman ps --format '{{.Names}}'` → `podman top <name> pid,args` | `claude --permission-mode auto` を含む行がある |
| 実モード表示 | 起動したセッションで permission mode の表示（`/status` 等）を採取 | 表示をそのまま結果ファイルへ転記。auto と表示されれば有効、Manual なら「引数は受理されたが auto は利用不可」と区別して記録。表示が得られなければ `not run` と理由 |
| 再ビルド後の `--check` | `./c3c claude --check <対象 dir>` | ドリフトの `[WARN]` が消える |
| Codex 起動回帰 | `./c3c codex <対象 dir>`（承認記録が無ければ preflight の `[y/N]` に `y`） | verify の `一致` を経て Codex が起動する。終了後の終了コードを記録 |
| MCP ゲート実機 | stdio 型 `.mcp.json` を持つ使い捨て dir で `./c3c claude <dir>` | 任意。`[y/N]` で `n` → `ERROR: MCP stdio 型サーバーの確認が拒否されました` で終了。実施しなければ `not run`（単体テストが同じ経路を検査済み） |
| CI | PR の `ci.yml` | lint・`--validator-only`・`--launcher-only`・hook テストが成功 |

各項目は「実測した」「テストが通った」「環境制約で not run」を区別して結果ファイルと PR 本文に書く。実 argv の確認と実モード表示の確認は別項目として報告する。

## 利用側への帰結（README に反映する内容の要約）

- 旧イメージは `-b` まで従来の既定のまま動き、起動時と `--check` の WARN が再ビルドの合図（`guard_asset_drift()` は fail-open。fail-closed へは変えない）。
- 引数を受理しない版を `CLAUDE_CODE_VERSION` で固定している利用者は起動が失敗する（再試行なし）。
- auto が利用できないセッションでは Claude Code 本体が Manual に戻り、確認プロンプトが出る。c3c は bypass に戻さない。
- 利用側の設定形式・CLI 引数は変わらない。移行作業は `-b` のみ。

## バージョンと PR

- README「バージョニング」の定義では既定挙動の変更は MAJOR に当たる。番号の提案は実装のコミット完了後に `git tag -l 'v*' | sort -V | tail -1` と README の記述を確認してから行い、タグ付与は持ち主承認後に `release-tag` skill で行う（自動作成しない）。「`--check` が当該変更を検出できることの実機確認」は上表の旧イメージ行が兼ねる。
- ブランチ `c3c/auto-permission-mode`（専用 worktree、main `6150cc5` 起点）。push と PR 作成は既存の承認規則どおり持ち主確認の上で行い、PR 本文は日本語、末尾に `— <実モデル名> (c3c)` で署名。PR 後は Fable と Codex（`codex exec --sandbox read-only`）の二重レビュー、マージは 3 条件が揃ったときにレビューした Claude セッションが行う。
- `trial/auto-permission-mode` ブランチとその worktree はマージ後に不要になるが、削除は持ち主判断（本計画では触らない）。

## 実装: Opus

根拠: 変更行はミッション定義そのもの（セキュリティ境界）で、README「セキュリティモデル」節の書き換えを伴う。Task 1 と実起動の計測結果（受理しない／受理するが Manual／auto）で進退と文書の書き方が変わる判断が残り、Codex の逐語手順には固定しきれない。
