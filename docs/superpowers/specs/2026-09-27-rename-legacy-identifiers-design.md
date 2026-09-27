# 旧製品名 claude-container の識別子を c3c へ改名する 設計

**状態:** 設計の合意済み（持ち主 2026-09-27）。spec の二重レビューは収束（Codex・Claude とも「実装計画に渡せる」）。持ち主の spec レビュー待ち。
**区分:** 境界（ファイアウォールを無効化する env キー、MCP・project 設定の承認記録と秘密のマウント先、`docs/development-invariants.md` の不変条件に触れる）。
**関連:** [増分移行の設計](2026-09-20-c3c-incremental-design.md) の第2段階（136・141・191 行目の「内部識別子の見た目だけの改名は行わない」「`CLAUDE_CONTAINER_*` は互換のため維持」）を、本設計で持ち主の判断により見直す。

## 目的

文章とコメントの旧製品名は #179 までで c3c に置き換えた。残る識別子（env キー、ホストの state directory、イメージ label、コンテナ内のパス、旧設定ディレクトリ `.claude-container.d/` の互換読み取り）からも旧名をなくす。

成功条件:

- 第 2 段の完了後、製品のコード・設定・README が旧名 `claude-container` を識別子として読み書きしない。旧名が残るのは、旧配置を検出して移行を案内する診断と、下記「範囲外」だけ。
- 第 1 段の間は、利用者が何も変えなくても従来どおり動く（`-b` も強制しない）。旧名を使っていることは起動時の `WARNING` と `--check` の `[WARN]` で分かる。
- 第 2 段で旧名が残っている利用者は、`c3c --check` で旧 env キー・旧設定ディレクトリ・旧 state・旧イメージの 4 種を検出でき、案内に従って移行できる。
- 承認記録・起動台帳・CLI 選択の記憶は、第 1 段の通常起動で自動的に新 state へ引き継がれる（上書きしない rename が使えない環境では、旧 state を使い続けて手動の移行を案内する）。

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

- `ENV_FILE_ALLOWED_KEYS` に `C3C_IPV6`・`C3C_NO_FIREWALL` を足す。旧キーも許可リストに残す。E7（`test-build.sh`）は許可リストと README「環境変数」節の表の完全一致を見るので、第 1 段の表には新旧 4 キーの行を置く（旧キーの行は「第 2 段で削除。新キーを使う」と書く）。
- キーの対の解決は `guard_*` 関数（`guard_fail`/`guard_warn` 経由）として、dispatch の呼び出し列で通常起動と `--check` の両方に通す（`docs/development-invariants.md` の guard 共用の不変条件）。env ファイルが無い `--check` でも、シェル環境の値に対して解決する。解決の規則:
  - 新旧の両方が空でない値で設定されている → `ERROR` で起動を中止（値が同じでも混ぜない。`--check` は `[FAIL]`）。`.c3c/env` とシェル環境のどちらから来たかは問わない。
  - 旧だけが空でない → `WARNING` で新キー名への書き換えを勧め（`--check` は `[WARN]`）、値を新キーへ写す。
  - 解決の後は旧キーを unset し、以降の launcher 内部（`guard_ipv6()`・`NO_FIREWALL=1` の警告・compose の補間）は新キーだけを正とする。
  - `C3C_*` を readonly にしない（許可リストのキーを readonly にすると、`load_env_file()` の無条件 export が bash の生エラーで落ちる。`c3c` の許可リスト直上の注意）。
- 空文字は「未設定」と同じに扱う（現行の `${VAR:-}` と同じ。空の export で誤って二重設定と判定しない）。
- `compose.yml` はコンテナ側の `C3C_NO_FIREWALL` と `CLAUDE_CONTAINER_NO_FIREWALL` の両方を、ホスト側の新キー `${C3C_NO_FIREWALL:-}` から補間する（ホスト側の旧キーからは補間しない。旧キーから補間すると、`.c3c/env` を新キーへ書き換えた利用者の旧イメージでファイアウォール無効化が黙って効かなくなる）。IPv6 は固定値なので、`compose.yml`（`"0"`）と `compose.ipv6.yml`（`"1"`）の両方に新旧両方の名前で書く。
- 第 1 段の `entrypoint.sh` は新キーを優先し、未設定・空なら旧キーを読む（旧 launcher・旧 compose で新イメージを起動したとき＝ロールバックでも、旧 compose が渡す旧キーで従来どおり効かせるため）。新旧の両方が空でなく値が違えば、firewall 適用前に `ERROR` で停止する（新 compose は同じ値を渡すので通常は起きない。fail-closed）。旧イメージの `entrypoint.sh` は旧キーを読む。これで新旧 launcher × 新旧イメージの 4 通りすべてで、`-b` なしにファイアウォール無効化・IPv6 のモードが従来どおり効く。
- 利用者が書く `C3C_` 接頭辞のキーは許可リストの 2 つだけ。launcher 内部の `C3C_PREF_KEY`・`C3C_GITCONFIG_SOURCE` 等は許可リスト外で、`.c3c/env` からは設定できない（従来どおり）。
- `.c3c/env` を grep する `NO_FIREWALL=1` の警告（`c3c` の `guard_*`）は、新旧どちらのキー名でも出す。
- 旧 launcher は `.c3c/env` の `C3C_*` を「解釈しない」`WARNING` 付きで無視する。新キーへ書き換えた後に旧版へ戻すと、ファイアウォール無効化と IPv6 は効かない（有効・IPv4 のまま＝安全側）。README とタグ本文のロールバックの説明に書く。

### `C3C_DIR`

`c3c` の compose 呼び出し 4 か所、`compose.yml` の `dockerfile:`、CI の env を同時に置き換える。同じ checkout で配られるため互換は持たない。

### state directory の自動移行

- `CC_STATE_DIR` を `$HOME/.local/state/c3c` にする。`MCP_APPROVAL_STORE`・`clean_all()` の `approval_store` 等の `$HOME/.local/state/claude-container/...` の直書きも state directory の変数由来へ揃える。`agent-preference.py` は launcher から state directory を受け取るので変更不要。
- 移行は**通常起動でだけ**行う。`--check`・`--clean`・`--clean <dir>` は移行しない（`--clean` は選択記憶を「読まない・書かない・消さない」不変条件を持ち、state 全体の移設はその保存場所を動かすため）。
- 移行の位置: 引数解析の後、state に触れる最初の処理より前。具体的には `resolve_project_directory()`（起動台帳の読み取り）・agent-preference の read・`freeze_project_paths()` のいずれよりも前で、state directory の変数を readonly にした後。
- 判定は lstat（symlink を辿らない）で行う。遷移表:

  | 旧 `~/.local/state/claude-container` | 新 `~/.local/state/c3c` | 通常起動 |
  |---|---|---|
  | 無い | 任意 | 何もしない |
  | ディレクトリ、またはディレクトリへ解決できる symlink | 無い（壊れた symlink も「ある」） | 旧の**エントリ自体**を新の名前へ rename する（symlink ならリンクそのものが移り、指す先は変わらない。現行で旧 state を symlink にしている利用も引き継がれる）。成功したら `WARNING` で移行を 1 回知らせる |
  | ファイル・壊れた symlink 等 | 無い | 移さない。旧の残存を `WARNING` で知らせる（現行でも旧がこの型なら state を使えない） |
  | ある（型を問わず） | ある（型を問わず） | 新を使う。旧の残存を `WARNING` で知らせ、「旧版の c3c のセッションがすべて終わってから中身を確認して削除する」と案内する。自動削除はしない |

  新の型の検査（ファイル等で使えない場合）は、従来の旧 state と同じく各処理（`mkdir -p`・`ensure_private_dir` 等）に任せる。
- rename の手段は、rename(2) 系だけを行いコピーへフォールバックしないこと（GNU `mv` は EXDEV でコピーと削除に切り替わるので使わない）と、移動先を**原子的に**上書きしないこと（renameat2 の `RENAME_NOREPLACE`）を必須とし、具体的な実装（python3 の ctypes 等）は計画で選ぶ。事前の非存在確認だけでは、確認と rename の間に現れた移動先を上書きしうるので代用にしない。上書きしない rename が使えない場合（ホストに python3 が無い、ファイルシステムが `RENAME_NOREPLACE` に対応しない等）は移行せず、**この起動では旧 state をそのまま使う**（第 1 段の前と同じ挙動。承認記録・台帳・選択記憶はそのまま効く）。`WARNING` で理由と手動の移行手順（c3c のセッションがすべて終わってから `mv ~/.local/state/claude-container ~/.local/state/c3c`）を案内する。新 state を作らないので、次回以降も同じ判定になり、「新旧の両方がある」状態へ落ちない。
- 成功の判定: rename の前に旧エントリの lstat の (st_dev, st_ino) を記録する。rename が失敗しても、その後に新エントリの lstat の (st_dev, st_ino) が記録と一致すれば、並行起動が先に移したとみなし成功扱いにする。一致しない・新が無い場合は `ERROR` で中止する（承認記録を黙って空にしない）。
- `--check` は書き込まない。旧が上表で「rename する」型で新が無ければ、起動台帳・承認記録の読み取りに旧を使い（`--check` は選択記憶を読まない）、次の通常起動で移行する旨を `[WARN]` で出す。新旧の両方があれば `[WARN]`。判定は通常起動と同じ lstat の規則にする（`-d` で symlink を辿って、`--check` だけが旧を読む食い違いを作らない）。
- `--clean`・`--clean <dir>` も移行しない。台帳の読み取り（`--clean <dir>` の削除済みパスの照合）は `--check` と同じ規則で新、無ければ旧を読む。`--clean`（全体）は新旧どちらの承認記録と台帳も削除する（選択記憶 `agent-preferences/` は従来どおり新旧とも消さない）。
- 実効の読み先（新か旧か）は、state directory の変数を readonly にする時点（`load_env_file()` より前。#39）で確定し、env から変えられない性質を保つ。
- 旧版へ戻したとき・古い checkout を動かしたとき: 旧版の c3c は旧 state を空から作り直すため、承認の確認がもう一度出て、起動台帳は空になる。移行前から走っていた旧版のセッションが終了時に選択記憶を書く場合も、旧 state が作り直される。いずれも新版では「新旧の両方がある」の `WARNING` になる。README とタグ本文に書く。

### label

- `Dockerfile.claude` は `io.c3c.*` と旧 `claude-container.*` の両方を書く（旧版の c3c へ戻したときに、ドリフト検知・IPv6 対応確認・`--clean-missing` が働くように）。配置は既存の不変条件に従う: 由来 label は全命令の最後の単一 `LABEL` に新旧 6 つを入れる（`docs/development-invariants.md` の由来 label の節）。`io.c3c.asset-hash` は旧と同じく CACHEBUST を消費する `RUN` より後に置く。
- 読み取りの fallback の単位:
  - 単独のキー（`asset-hash`・`base-image`・`ipv6-support`）はキーごとに、`io.c3c.*` の値があればそれを、空か欠落なら旧を読む（`podman image inspect` の `index` は欠落キーにも空文字を返し、両者を区別できないため）（`guard_asset_drift()`・`guard_ipv6()`）。
  - 由来 label（`project-metadata`・`project-path`・`project-name`）は**組単位**で選ぶ。`io.c3c.project-*` が 1 つでもあれば新の組だけを使い（不完全なら従来どおり不完全として扱い、旧で補わない）、1 つも無いときだけ旧の組を使う。新旧の組を混ぜない（`docs/development-invariants.md` の「不完全な由来ラベルを旧形式照合へフォールバックしない」を保つ）。
  - `project-images.py` の `relevant` 判定（名前なしイメージ）は、従来の `claude-container.` 前方一致を残したうえで、新の由来 label（`io.c3c.project-*`）のキーを持つものも加える。`io.c3c.` の前方一致にはしない（`io.c3c.codex-audit-protocol` 等は既存の全イメージに付くので、判定が広がる）。旧の前方一致を残すのは、第 1 段より前の名前なしイメージの判定を狭めないため（実装計画のレビューで確定）。
- `Dockerfile.claude` の変更で境界アセットのハッシュが変わるため、既存イメージでは `-b` まで起動時と `--check` でドリフトの `WARNING` が出る（起動は止まらない。v14.1.x と同じ扱い。`Dockerfile.claude`・compose がハッシュ対象かは計画で `ASSET_HASH_TARGETS` を確認する）。

### コンテナ内のパス

- 秘密: `compose.yml` で `SECRETS_DIR` を新旧両方のパスへ `:ro` でマウントする。README の案内（`cat /home/node/.config/.../GITHUB_ISSUES_PAT` 等）は新パスにする。旧イメージのままでも新パスが使えるので、利用者は第 2 段までに自分のスクリプト・MCP 設定を移せる。`git-askpass.sh`・`entrypoint.sh` の `SECRETS_MOUNT` は第 1 段では旧パスのまま（旧イメージ・旧 launcher との整合のため）。
- `lint.sh` の `:ro` 検査を秘密の新旧両方のマウントへ広げる（現在は承認記録 3 種と `.gitconfig` だけを見ているので、秘密の検査は追加になる）。`lint.sh` の IPv6 の needle（`CLAUDE_CONTAINER_IPV6: '1'`）は新旧両方を見るようにする。
- `/etc/claude-container/*` は第 1 段では変えない。

### 文書

- README: env キーの表・例・秘密の案内・state のパス・label 名を新名にし、旧名が移行期間中も読めること、ロールバック時の挙動（env キー・state）、第 2 段へ上げる前に `c3c --check --clean-missing` を実行しておくことを書く。
- `docs/development-invariants.md`: state directory と移行・label の fallback の単位・秘密の二重マウント・env キーの対の解決を反映する。
- タグ本文: 旧名はそのまま動くこと、書き換えの対応表、`-b` 推奨（ドリフト WARNING）、ロールバック時の挙動、第 2 段の予告と事前の `--clean-missing`。

## 第 2 段（MAJOR）: 互換読み取りを削除し、旧名は検出と案内だけにする

第 2 段の詳細は第 2 段の計画で定める。spec で決めておくのは次の方針。

- **env キー**: 旧キーを許可リストから外す。許可リスト外のキーは `load_env_file()` で export されず汎用の「解釈しない」`WARNING` になるだけなので、`guard_legacy_vars()` と同じく `.c3c/env` の行とシェル環境の両方を見る専用の guard を置き、旧キーが空でない値であれば `ERROR` で中止して新キー名を案内する（`--check` は `[FAIL]`）。compose と `entrypoint.sh` は新キーだけを扱う。
- **`.claude-container.d/`**: 互換読み取りを削除する。旧名が存在すれば（型を問わず、`.c3c` の有無も問わず）`ERROR` で中止し `mv` の手順を案内する（`--check` は `[FAIL]`）。`.gitignore` の旧名の行を削除する。
- **state**: 自動移行を削除する。旧 state が残っていれば `WARNING` で `mv` のコマンドを案内し、新だけを使う（移さずに進めると承認の確認がもう一度出る。確認の側に倒れる）。第 1 段を経ずに上げた利用者は台帳が旧 state 側にしかなく、引数なしの `--check` が「台帳が空」になるため、旧台帳を診断のためだけに読み取り専用で参照するか、「旧 state を移してから再実行する」2 段の手順を案内するかを第 2 段の計画で決める。
- **label**: `io.c3c.*` だけを書き、読む。新しい label `io.c3c.image-layout`（値は `"2"`）を足し、これが対応値でないイメージは `ERROR` で `-b` を案内して止める（`--check` は `[FAIL]`）。第 2 段の compose は `/etc/c3c/*` と新しい秘密のパスにだけマウントし、旧イメージの `entrypoint.sh` はそこを読まないため。仕組みは `guard_codex_image_support()` と同じ型にする。
- **旧 label だけのイメージ**: 旧 label の検出は**診断専用**の処理とし、通常の由来判定・削除判定には入れない。台帳なし・元パス欠落・名前なしのイメージも検出して `--check` の `[WARN]` で示す。清掃の案内は、`c3c --clean <dir>` が使える場合（台帳に一致する）はそれを、使えない場合はイメージ ID を示して `podman rmi` での手動確認・削除を案内する。
- **コンテナ内のパス**: `/etc/c3c/*` へ移し、秘密は新パスだけにマウントする。対象は `Dockerfile.claude`・`compose.yml`・`entrypoint.sh`・`init-firewall.sh`・`ipv6-firewall.py`・`git-askpass.sh`・`lint.sh`（承認記録の `:ro` 検査のパス）・`docs/development-invariants.md`・テスト。
- **README**: 「旧名も移行期間中は読める」の記述を削除し、移行手順を「旧名からの移行（v16）」の 1 節にまとめる。
- **SemVer**: MAJOR。タグの提案前に、`--check` が 4 種（旧 env キー・旧設定ディレクトリ・旧 state・旧イメージ）を検出することを実機で確認する。
- **着手時期**: 第 1 段のタグ付与後、持ち主が自分の利用側プロジェクトを移し終えてから。日付では決めない。第 2 段の実装計画はその時点で起こす。

## 検証

第 1 段:

- 単体・launcher テスト（`tests/`）:
  - env キー: 新だけ・旧だけ（`WARN` と値の写し）・両方（`ERROR`）を、`.c3c/env` とシェル環境のそれぞれで。空文字は未設定扱い。env ファイルが無い `--check`。
  - `entrypoint.sh`: 新だけ・旧だけ・同値の両方・異なる値の両方（firewall 前に停止）。
  - state 移行: 遷移表の各行（旧がディレクトリ・ディレクトリへの symlink・ファイル・壊れた symlink、新の有無）。rename 失敗後に新の同一性が一致する（競合成功）・一致しない・新が無い（`ERROR`）。`--check` が移行も書き込みもしないこと。`--clean`・`--clean <dir>` が移行しないこと（削除以外を書かないこと）。上書きしない rename が使えない場合に旧 state を使い続け、新 state を作らないこと。`--check` と `--clean <dir>` が新が無いとき旧の台帳を読むこと。
  - label: 単独キーの新優先と旧 fallback（`guard_asset_drift`・`guard_ipv6`）。由来 label の組単位の選択: 新の組が不完全で旧の組が完全なイメージが `--clean-missing` の削除候補にならないこと。新旧の組が別のパスを指すイメージで新だけが使われること。
- `lint.sh`: compose 回帰テストで秘密の新旧マウントの `:ro`、新旧の env キーがコンテナへ新キーの値で渡ること、IPv6 override の新旧 needle。
- `test-build.sh` の該当モード（README「変更後の確認」節で確定する）。
- 実機（新旧 launcher × 新旧イメージの組み合わせ）: `-b` しない旧イメージを新 launcher で、新イメージを旧 launcher（第 1 段の直前のタグの checkout）で起動し、`NO_FIREWALL`・`IPV6` が効くこと。秘密が新パスで読めること。持ち主の実 state が移行されること（移行前に `cp -a` で退避）。

第 2 段: `--check` の 4 種の検出、`image-layout` ゲートが旧イメージを止めること、`-b` 後に全経路（Claude・Codex・IPv6・秘密・承認記録）が動くこと。詳細は第 2 段の計画で定める。

## 進め方

- 区分は境界。計画・実装完了時（PR 前）・PR 後の 3 段階で、Codex と作成に関わっていない Claude の二重レビューを行う。
- 推奨実装は Opus（秘密のマウント先を変える＝秘密を読む経路に触れる）。持ち主の指定を待つ。
- 実装計画は第 1 段だけを先に `docs/superpowers/plans/` へ書く。

## spec レビューの記録

- 1 巡目（対象 4d99546）: Codex（gpt-6-astra、`codex exec --sandbox read-only`）は「修正後に渡せる」、Critical 0・Important 5・Minor 1。Claude（claude-opus-5-5、headless `claude -p` 読み取り専用。`modelUsage` で確認）は「修正後に渡せる」、Critical 0・Important 2・Minor 9。両者共通の Important は、新イメージ × 旧 launcher で env キーが効かない点と、由来 label の fallback の単位が未定義な点。Codex 固有の Important（state 移行の成功判定、旧 state が symlink の利用の引き継ぎ、第 2 段の旧イメージ清掃の案内）と全 Minor を反映した。
- 確認限定巡（対象 93796b2）: Claude は前回 11 件すべて「直った」、判定「実装計画に渡せる」。新たな矛盾 2 件（`--check` は選択記憶を読まない、python3 不在時の移行の機会）を指摘。Codex は Important 5 件中 4 件「直った」、Important 2（原子的な非上書き）が「一部」、判定「修正後に渡せる」。新たな矛盾 2 件（python3 不在時と成功条件、`--clean` の書き込み）を指摘。いずれも反映した。
- 確認限定巡 2 回目（対象 c952ee3、Codex のみ）: Important 2 と新たな矛盾 2 件がすべて「直った」、判定「実装計画に渡せる」。
