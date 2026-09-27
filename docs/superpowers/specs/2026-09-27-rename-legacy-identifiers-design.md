# 旧製品名 claude-container の識別子を c3c へ改名する 設計

**状態:** 設計の合意済み（持ち主 2026-09-27）。計画レビュー前。
**区分:** 境界（ファイアウォールを無効化する env キー、MCP・project 設定の承認記録と秘密のマウント先、`docs/development-invariants.md` の不変条件に触れる）。
**関連:** [増分移行の設計](2026-09-20-c3c-incremental-design.md) の第2段階（136・141・191 行目の「内部識別子の見た目だけの改名は行わない」「`CLAUDE_CONTAINER_*` は互換のため維持」）を、本設計で持ち主の判断により見直す。

## 目的

文章とコメントの旧製品名は #179 までで c3c に置き換えた。残る識別子（env キー、ホストの state directory、イメージ label、コンテナ内のパス、旧設定ディレクトリ `.claude-container.d/` の互換読み取り）からも旧名をなくす。

成功条件:

- 第 2 段の完了後、製品のコード・設定・README が旧名 `claude-container` を識別子として読み書きしない。旧名が残るのは、旧配置を検出して移行を案内する診断と、下記「範囲外」だけ。
- 第 1 段の間は、利用者が何も変えなくても従来どおり動く（`-b` も強制しない）。旧名を使っていることは起動時の `WARNING` と `--check` の `[WARN]` で分かる。
- 第 2 段で旧名が残っている利用者は、`c3c --check` で旧 env キー・旧設定ディレクトリ・旧 state・旧イメージの 4 種を検出でき、案内に従って移行できる。
- 承認記録・起動台帳・CLI 選択の記憶は、第 1 段の通常起動で自動的に新 state へ引き継がれる。

## 名前の対応

| 旧 | 新 | 備考 |
|---|---|---|
| `CLAUDE_CONTAINER_IPV6` | `C3C_IPV6` | 利用者が `.c3c/env` かシェル環境で書く |
| `CLAUDE_CONTAINER_NO_FIREWALL` | `C3C_NO_FIREWALL` | 同上 |
| `CLAUDE_CONTAINER_DIR` | `C3C_DIR` | launcher → compose の内部変数。CI（`.github/workflows/ci.yml`）も設定する。env の許可リスト外 |
| `~/.local/state/claude-container/` | `~/.local/state/c3c/` | 中身（`projects`・`mcp-approvals/`・`agent-preferences/`）の構成は変えない |
| label `claude-container.asset-hash` / `base-image` / `ipv6-support` | `io.c3c.asset-hash` / `io.c3c.base-image` / `io.c3c.ipv6-support` | 既存の `io.c3c.codex-audit-protocol` と名前空間を揃える |
| label `claude-container.project-metadata` / `project-path` / `project-name` | `io.c3c.project-metadata` / `io.c3c.project-path` / `io.c3c.project-name` | `project-images.py` が読む |
| `/etc/claude-container/*` | `/etc/c3c/*` | 許可ドメイン・ポート、GitHub meta、3 種の承認記録のマウント先 |
| `/home/node/.config/claude-container/secrets` | `/home/node/.config/c3c/secrets` | `SECRETS_DIR` のマウント先。README で利用者に案内している |
| README の例 `~/.config/claude-container/secrets.d/<project>` | `~/.config/c3c/secrets.d/<project>` | 例示だけ。利用者が実際に置いたホストのパスは変えない |
| `.claude-container.d/` の互換読み取り、`.gitignore` の `.claude-container.d/env` | 第 2 段で削除 | 残っていれば検出して案内 |

### 範囲外

- `CC_*` の内部変数（`CC_AGENT`・`CC_STATE_DIR` 等）: 旧名の文字列ではない。
- compose のサービス名とイメージ名の接尾辞 `_claude-auth-workspace`: 旧名の文字列ではなく、変えると全イメージの名前が変わる。必要なら別課題。
- レガシー共有イメージ `localhost/claude-container_claude-auth-workspace`: 現れるのは `clean_all()` のコメントだけで、清掃は汎用の正規表現 `^localhost/.+_claude-auth-workspace$` で拾う。識別子として扱っていないので変えない（コメントは第 2 段で整理してよい）。
- upstream（sethjensen1/claude-container）の帰属表示と LICENSE、過去の Issue・PR・実行ログの URL（`jj1xgo/claude-container/...` は GitHub が転送する）。
- `docs/superpowers/plans/`・`specs/` の過去の記録、vault の記述。
- 旧入口 `claude-container` の移行表（README「旧コマンドからの移行」節）: 旧コマンド名の案内として残す。

## 第 1 段（MINOR）: 新名を正とし、旧名は WARNING 付きで動かし続ける

### env キー

- `ENV_FILE_ALLOWED_KEYS` に `C3C_IPV6`・`C3C_NO_FIREWALL` を足す。旧キーも許可リストに残す。README「環境変数」節の表と E7 の一致検査も合わせる。
- `load_env_file()` の後（通常起動・`--check` とも）に、キーの対ごとに解決する:
  - 新旧の両方が空でない値で設定されている → `ERROR` で起動を中止（値が同じでも混ぜない。`--check` は `[FAIL]`）。`.c3c/env` とシェル環境のどちらから来たかは問わない。
  - 旧だけが空でない → `WARNING` で新キー名への書き換えを勧め（`--check` は `[WARN]`）、値を新キーへ写す。
  - 解決の後は旧キーを unset し、以降の launcher 内部（`guard_ipv6()`・`NO_FIREWALL=1` の警告・compose の補間）は新キーだけを正とする。
- 空文字は「未設定」と同じに扱う（現行の `${VAR:-}` と同じ。空の export で誤って二重設定と判定しない）。
- `compose.yml` はコンテナ側の `C3C_NO_FIREWALL` と `CLAUDE_CONTAINER_NO_FIREWALL` の両方を、ホスト側の新キー `${C3C_NO_FIREWALL:-}` から補間する（ホスト側の旧キーからは補間しない。旧キーから補間すると、`.c3c/env` を新キーへ書き換えた利用者の旧イメージでファイアウォール無効化が黙って効かなくなる）。IPv6 は固定値なので、`compose.yml`（`"0"`）と `compose.ipv6.yml`（`"1"`）の両方に新旧両方の名前で書く。第 1 段の新しいイメージの `entrypoint.sh` は新キーを読み、旧イメージの `entrypoint.sh` は旧キーを読むため、`-b` しなくてもファイアウォール無効化・IPv6 のモードが従来どおり効く。
- 利用者が書く `C3C_` 接頭辞のキーは許可リストの 2 つだけ。launcher 内部の `C3C_PREF_KEY`・`C3C_GITCONFIG_SOURCE` 等は許可リスト外で、`.c3c/env` からは設定できない（従来どおり）。
- `.c3c/env` を grep する `NO_FIREWALL=1` の警告（`c3c` の `guard_*`）は、新旧どちらのキー名でも出す。

### `C3C_DIR`

`c3c` の compose 呼び出し 4 か所、`compose.yml` の `dockerfile:`、CI の env を同時に置き換える。同じ checkout で配られるため互換は持たない。

### state directory の自動移行

- `CC_STATE_DIR` を `$HOME/.local/state/c3c` にする。`MCP_APPROVAL_STORE` 等の `$HOME/.local/state/claude-container/...` の直書きも `CC_STATE_DIR` 由来へ揃える。`agent-preference.py` は launcher から state directory を受け取るので変更不要。
- 移行は通常起動と `--clean` で、state に触れる最初の処理より前、`CC_STATE_DIR` を readonly にした後に 1 回行う:
  - 旧 `$HOME/.local/state/claude-container` がディレクトリ（symlink でない）で、新が存在しない（symlink・壊れた symlink も「存在」）→ 同じ親ディレクトリ内で rename(2) する（GNU `mv -T` 相当。コピーにフォールバックしない）。成功したら `WARNING` で移行を 1 回知らせる。
  - rename が失敗し、その後に新がディレクトリとして存在する → 並行起動が先に移したとみなし成功扱い。新が無ければ `ERROR` で中止（承認記録を黙って空にしない）。
  - 新旧の両方がある → 新を使い、旧の残存を `WARNING` で知らせる（中身の確認と削除を案内。自動削除はしない）。
  - 旧が symlink・ファイル等 → 辿らず移さない。旧の残存を `WARNING` で知らせる。
- 移行は、agent-preference の read（前回 CLI の記憶の読み取り）と `freeze_project_paths()` より前に行う。
- `--check` は書き込まない。新が無く旧がディレクトリなら、起動台帳・承認記録の読み取りに旧を使い、次の通常起動で移行する旨を `[WARN]` で出す。新旧の両方があれば `[WARN]`。実効の読み先は、`CC_STATE_DIR`・`MCP_APPROVAL_STORE` を readonly にする時点（`load_env_file()` より前。#39）で確定し、env から変えられない性質を保つ。具体的な置き場所は計画で定める。
- `--clean`（全体）は新旧どちらの承認記録と台帳も削除する。
- 旧版へ戻したとき・古い checkout を動かしたとき: 旧版の c3c は旧 state を空から作り直すため、承認の確認がもう一度出て、起動台帳は空になる。その後に新版へ戻ると「新旧の両方がある」の `WARNING` が出続けるので、旧 state の中身を確認して削除する。README とタグ本文に書く。

### label

- `Dockerfile.claude` は `io.c3c.*` と旧 `claude-container.*` の両方を書く（旧版の c3c へ戻したときに、ドリフト検知・IPv6 対応確認・`--clean-missing` が働くように）。
- 読み取りは `io.c3c.*` を優先し、無ければ旧 label に fallback する: `guard_asset_drift()`・`guard_ipv6()`・`project-images.py`（`LABELS` と `claude-container.` の前方一致）。
- `Dockerfile.claude` の変更で境界アセットのハッシュが変わるため、既存イメージでは `-b` まで起動時と `--check` でドリフトの `WARNING` が出る（起動は止まらない。v14.1.x と同じ扱い）。

### コンテナ内のパス

- 秘密: `compose.yml` で `SECRETS_DIR` を新旧両方のパスへ `:ro` でマウントする。README の案内（`cat /home/node/.config/.../GITHUB_ISSUES_PAT` 等）は新パスにする。旧イメージのままでも新パスが使えるので、利用者は第 2 段までに自分のスクリプト・MCP 設定を移せる。`git-askpass.sh`・`entrypoint.sh` の `SECRETS_MOUNT` は第 1 段では旧パスのまま（旧イメージとの整合のため）。
- `lint.sh` の `:ro` 検査を秘密の新旧両方のマウントへ広げる（現在は承認記録 3 種と `.gitconfig` だけを見ているので、秘密の検査は追加になる）。
- `/etc/claude-container/*` は第 1 段では変えない。

### 文書

- README: env キーの表・例・秘密の案内・state のパス・label 名を新名にし、旧名が移行期間中も読めることと、第 2 段へ上げる前に `c3c --check --clean-missing` を実行しておくことを書く。
- `docs/development-invariants.md`: state directory・label・秘密の二重マウント・env キーの対の解決を反映する。
- タグ本文: 旧名はそのまま動くこと、書き換えの対応表、`-b` 推奨（ドリフト WARNING）、第 2 段の予告と事前の `--clean-missing`。

## 第 2 段（MAJOR）: 互換読み取りを削除し、旧名は検出と案内だけにする

- **env キー**: 旧キーを許可リストから外し、`.c3c/env` かシェル環境に空でない値で設定されていれば `ERROR` で中止して新キー名を案内する（`--check` は `[FAIL]`）。compose は新キーだけを渡す。
- **`.claude-container.d/`**: 互換読み取りを削除する。旧名が存在すれば（型を問わず、`.c3c` の有無も問わず）`ERROR` で中止し `mv` の手順を案内する（`--check` は `[FAIL]`）。`.gitignore` の旧名の行を削除する。
- **state**: 自動移行を削除する。旧 state が残っていれば `WARNING` で `mv` のコマンドを案内し、新だけを使う（移さずに進めると承認の確認がもう一度出る。確認の側に倒れる）。
- **label**: `io.c3c.*` だけを書き、読む。新しい label `io.c3c.image-layout`（値は `"2"`）を足し、これが対応値でないイメージは `ERROR` で `-b` を案内して止める（`--check` は `[FAIL]`）。第 2 段の compose は `/etc/c3c/*` と新しい秘密のパスにだけマウントし、旧イメージの `entrypoint.sh` はそこを読まないため。仕組みは `guard_codex_image_support()` と同じ型にする。
- **旧 label だけのイメージ**: `--check` は `[WARN]` で示し `c3c --clean <dir>` を案内する（`--clean-missing` の自動清掃の対象からは外れる）。
- **コンテナ内のパス**: `/etc/c3c/*` へ移し、秘密は新パスだけにマウントする。対象は `Dockerfile.claude`・`compose.yml`・`entrypoint.sh`・`init-firewall.sh`・`ipv6-firewall.py`・`git-askpass.sh`・`lint.sh`・`docs/development-invariants.md`・テスト。
- **README**: 「旧名も移行期間中は読める」の記述を削除し、移行手順を「旧名からの移行（v16）」の 1 節にまとめる。
- **SemVer**: MAJOR。タグの提案前に、`--check` が 4 種（旧 env キー・旧設定ディレクトリ・旧 state・旧イメージ）を検出することを実機で確認する。
- **着手時期**: 第 1 段のタグ付与後、持ち主が自分の利用側プロジェクトを移し終えてから。日付では決めない。第 2 段の実装計画はその時点で起こす。

## 検証

第 1 段:

- 単体・launcher テスト（`tests/`）:
  - env キー: 新だけ・旧だけ（`WARN` と値の写し）・両方（`ERROR`）を、`.c3c/env` とシェル環境のそれぞれで。空文字は未設定扱い。
  - state 移行: 旧だけ（rename）、両方、旧が symlink、rename 失敗後に新がある（競合）・無い（`ERROR`）。`--check` が書き込まないこと。
  - label: 新 label 優先、旧 label への fallback（`guard_asset_drift`・`guard_ipv6`・`project-images.py`）。
- `lint.sh`: compose 回帰テストで秘密の新旧マウントの `:ro` と、新旧の env キーがコンテナへ渡ること。
- `test-build.sh` の該当モード（README「変更後の確認」節で確定する）。
- 実機: `-b` しない旧イメージで、旧キー・新キーそれぞれの `NO_FIREWALL`・`IPV6` が効くこと、秘密が新パスで読めること。持ち主の実 state が移行されること（移行前に `cp -a` で退避）。

第 2 段: `--check` の 4 種の検出、`image-layout` ゲートが旧イメージを止めること、`-b` 後に全経路（Claude・Codex・IPv6・秘密・承認記録）が動くこと。詳細は第 2 段の計画で定める。

## 進め方

- 区分は境界。計画・実装完了時（PR 前）・PR 後の 3 段階で、Codex と作成に関わっていない Claude の二重レビューを行う。
- 推奨実装は Opus（秘密のマウント先を変える＝秘密を読む経路に触れる）。持ち主の指定を待つ。
- 実装計画は第 1 段だけを先に `docs/superpowers/plans/` へ書く。
