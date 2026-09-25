# CODEX_HOST_PLUGINS の検証記録

2026-09-24。対象: `41be0ff`（launcher）・`0e03e48`（Compose 検査）・`3fa0903`（文書）。
実装計画は [2026-09-24-codex-host-plugins.md](2026-09-24-codex-host-plugins.md)。

Task 1〜3 と受入前の指紋取得・A1 を 2026-09-24 に、A2〜A6 の対話受入を 2026-09-25 に実施し、すべて PASS。

## 自動検証

以下の初回検証は Task 1〜3 の実装時に実行した（launcher は `41be0ff` の内容、実マウントは `0e03e48` の内容）。レビュー後の修正に対する検証は末尾に別記する。

| コマンド | 結果 |
| --- | --- |
| `./lint.sh` | rc=0、警告ゼロ。Compose の単独・7 ファイル同時の設定、source 未設定・空の拒否を含む |
| `TMPDIR=/tmp ./test-build.sh --launcher-only` | rc=0、PASS=337 / FAIL=0 |
| `python3 -m unittest tests.test_codex_launch` | 35 tests、OK（実行時は bytecode 抑制なし。生成ファイルは除去） |
| `./test-build.sh --validator-only` | rc=0、PASS=82 / FAIL=0 |
| `bash examples/hooks/tests/test-block-pr-approve.sh` | rc=0、全ケース green |
| `TMPDIR=/tmp ./test-build.sh --build-only` | rc=0、PASS=17 / FAIL=0。Node 24.18.0・Codex CLI 0.156.0、CLI 起動・bubblewrap の配置と保護を確認 |
| `TMPDIR=/tmp ./test-build.sh --config-ro-only` | rc=0、PASS=83 / FAIL=0 |

実装前は launcher の新規 checks と Codex 経路の2テストが失敗し、実装後に通った。
`read_only: false` への一時変更は lint が対象 `/home/node/.codex/plugins/cache` の読み取り専用違反として検出し、rc=1。`true` へ復元後の lint は rc=0。

実 Podman では cache の読み取り、作成・追記・削除・置換・マウント点の削除の拒否、親 `plugins/` と専用 home への書き込み、source の不変、ホスト側の所有者を確認した。これは隔離した seed データを使うマウント試験であり、A2〜A6 の代替ではない。

環境と実行上の留保:

- workspace-write 内の検証はローカル socket の作成禁止と Podman 設定領域の read-only により失敗。上表の Compose・通信・実コンテナを含む検証は個別許可を得てホスト権限で実行した。
- ビルド時の GitHub meta 取得は HTTP 403。既存のスナップショットへの既定 fallback が働いた。最新の meta を取得できたという結果ではない。
- 最初のビルド検証では、実行中の `test-build.sh` を編集したためビルド後に syntax error。スクリプトを固定して全 `--build-only` を再実行し、上表の成功を確認した。
- GitHub 上の CI: not run（push・PR 作成は今回の範囲外）。上表はローカルの実行結果。

## A1: 有効化と診断

PASS。`/tmp` の隔離 fixture に専用 `CODEX_DIR` と `CLAUDE_CONFIG_DIR` を用意し、`.c3c/env` に `CODEX_HOST_PLUGINS=1`、専用 `config.toml` に `[plugins."superpowers@superpowers-dev"]` / `enabled = true` を設定した。認証ファイルはコピーも参照もしていない。

`./c3c --check --agent codex <fixture>` は rc=0。次の行を確認した（ホスト固有のパスは `~` に置換）:

```text
[OK]   Codex plugin 共有 (ro): ~/.codex/plugins/cache -> /home/node/.codex/plugins/cache
```

実行前後の fixture の型・mode・uid・mtime・パス・リンク先と通常ファイル内容を NUL 区切りで比較し一致（`cmp` は両方 rc=0）。`CODEX_DIR/plugins` 自体が作られていないことも確認した。未ビルド fixture と未作成の Claude placeholder による WARN はあるが FAIL はない。

計画の `cache_fingerprint`（`set -o pipefail`、NUL 区切り）で受入前のホストキャッシュ指紋を取得した（rc=0）:

```text
47ead4225dda800bd18fc3d284bd42337748e71ae2b6e85c449474e376f61e02
```

この指紋は A1 実施前の記録。A2〜A6 を別の時点で行う場合は、ホストでの通常更新と試験による変更を混同しないよう、対話受入の直前にも取得する。

## A2〜A6: 対話受入

2026-09-25、ホスト（codex-cli 0.156.1、superpowers 6.4.1）と `c3c codex -b` で再ビルドしたイメージ（コンテナ内 codex-cli 0.156.0）。対象コードは `ef45c40`（製品コードは `744b182` から不変）。対話起動と TUI の目視は持ち主、`podman exec`・ログ・指紋の確認は Claude の対話セッション（Opus 5.5）が行った。

準備（fixture の不足の補い。製品コードは変更していない）:

- `allowed-domains.txt` に `chatgpt.com`・`auth.openai.com`、専用 `config.toml` に `cli_auth_credentials_store = "file"` を追加した。
- 認証は既存の認証ファイルを複製せず、TUI の device code で fixture の専用 home へ新規ログインした（持ち主の選択）。認証ファイルの内容は表示・記録していない。
- 初回の起動は、`CLAUDE_CONFIG_DIR` の基点に `.claude.json` が無く、podman がその位置にディレクトリを作ってファイルのマウントに失敗した（検査用コンテナが rc=126 で止まり、本起動へ進まなかった）。既存の `compose.yml` の前提（基点に `.claude.json` が実在）で、本変更とは無関係。作られたディレクトリ（ホストのユーザー所有）を消して `{}` のファイルを置き、再起動した。

受入直前のキャッシュ指紋（A1 時点の値から変化していた。原因は未確認。受入の比較はこの値を基準にした）:

```text
bf6acf991155b270f02ad76f03c453c3c38b0b146cd08aa1581316b880134395
```

| 項目 | 結果 | 要点 |
| --- | --- | --- |
| A2: skill の読み込み | PASS | ホストと `podman exec` の `codex debug prompt-input hi` がどちらも rc=0、superpowers の skill 名 15 件が一致（`diff_rc=0`） |
| A3: 対話起動 | PASS | 下記 |
| A4: 書けないこと | PASS | 下記 |
| A5: Claude 経路 | PASS | `c3c claude` のコンテナ（`CC_AGENT=claude`）でもキャッシュが `ro` でマウントされ、`codex debug prompt-input hi` の skill 集合がホストと一致（rc=0、15 件、`diff_rc=0`） |
| A6: 無効化と有効化の行の残存 | PASS（記録） | 下記 |

**A3**: 起動エラーや marketplace 更新失敗の表示はなかった。TUI の警告（F2）は週の利用枠の残量だけ。`$superpowers:using-superpowers` で skill が選ばれ、実行された。起動以降の `logs_2.sqlite` を `marketplace`・`plugin`・`Permission denied`・`Read-only`・`os error` と WARN/ERROR で検索した結果:

- ChatGPT ログイン後、Codex はアカウント側で install された plugin（`openai-curated-remote` の `github`・`openai-templates`・`plugin-management`。ホストのキャッシュにあるもの）の同期を 3 回行い、そのたびにキャッシュ内の一時ファイル作成が `Read-only file system (os error 30)` で失敗した（WARN `failed to persist identity for cached remote installed plugin`）。同期は `failed_remote_plugin_ids` を記録して完了し、起動と superpowers の利用を妨げなかった。書込みを止めたのは `:ro` で、firewall ではない。
- ERROR 2 件は TUI の自己更新確認（`api.github.com` の 403 rate limit）で、本変更と無関係。ログイン前の featured plugin 取得の 401、同梱 curated marketplace の manifest の検証 WARN（`CODEX_DIR/.tmp/plugins`、rw の専用 home）も無関係。
- 専用 `config.toml` への書込みは TUI の状態（`[tui]` の表示済みフラグ）だけ。
- アカウント側の plugin が有効化なしに読み込まれていないかを、ホストの `codex debug prompt-input hi` の全文で確認した（同じアカウントでログイン済み、キャッシュに同じ 3 件がある）。skill として載るのは `config.toml` で有効にした superpowers だけで、`github` 等は `<recommended_plugins>`（available but not installed）の一覧に出るだけだった。コンテナ側は superpowers の skill 名だけを比較しており、全名前空間の列挙はしていない。

**A4**: コンテナ内の `touch ~/.codex/plugins/cache/probe` は `Read-only file system`（rc=1）、`mount` でも `ro`。`codex plugin marketplace upgrade superpowers-dev` は rc=1 で失敗した。ただし失敗理由は ``marketplace `superpowers-dev` is not configured as a Git marketplace`` で、コンテナ用の設定に marketplace の定義がないため書込みの前に止まった（計画の背景 4 のホストでの実測の `Permission denied` とは経路が違う）。`:ro` による書込み拒否そのものは `touch`、A3 の同期の失敗、実マウント試験の 83 件で確認している。A6 まで終えた後、ホストのキャッシュ指紋は rc=0 で受入前と一致（`cmp_rc=0`）。`find <CODEX_DIR> -not -uid $(id -u)` は出力なしで rc=0（fixture 全体でも 0 件）。

**A6**: `.c3c/env` から `CODEX_HOST_PLUGINS` だけを消し、専用 `config.toml` の `[plugins."superpowers@superpowers-dev"]` `enabled = true` は残して `c3c codex` で起動した。

- 起動は成功し、TUI に plugin 関係の表示はなかった。コンテナ内にキャッシュのマウントはなく、`~/.codex/plugins/cache` は空（ホストの plugin は見えない）。`$` の一覧と `codex debug prompt-input hi` に superpowers は出ない（0 件）。
- ログには `failed to load plugin: plugin is not installed plugin="superpowers@superpowers-dev"` の WARN が残るだけ。superpowers の install や marketplace の取得は試みなかった。
- アカウント側の plugin 3 件については bundle のダウンロード（`*.oaiusercontent.com`）を試み、許可リストにないため通信で失敗した（`failed_materialization_remote_plugin_ids`）。
- `CODEX_DIR/plugins` 配下への書込みはなかった（起動前後の一覧が一致し、起動以降の更新なし）。
- 推測（未実測）: 利用者がダウンロード先を許可した場合、アカウント側の plugin は rw の専用 `CODEX_DIR` の中に実体化されるとみられる。ホストのキャッシュには及ばない。

受入の fixture（新規ログインの認証を含む）は記録後に削除した。device code ログインのセッションはアカウント側に残る。

## 実装レビューと修正

初回対象: `d5f9cd1..df96db4`。作成に関与していない Codex（gpt-6-astra、read-only）を先に background 起動し、Claude（claude-opus-5-5、Read/Grep/Glob のみ）と独立にレビューした。

- Codex: With fixes。Important 1・Minor 1。`HOME` の先頭 `//` を `pwd -P` が保持し、正規化済み `CODEX_DIR` との包含比較で重なりを見逃すことを再現した。これは計画のコード例にもある欠陥。
- Claude: コードは Yes、Minor 6。A2〜A6 の完了前に機能全体の合格とはしない。初回 JSON は `subtype=success` / `is_error=false`、`modelUsage` で実効モデルを確認したが、ユーザーの継続入力時に元のコマンドの終了コード取得を失ったため、確認限定巡の終了も別途確認する。

修正: source と WARNING 用比較対象の先頭の重複 `/` を、既存の `guard_codex_dir()` と同じ規則で正規化した。新規回帰テスト3本（通常起動と `--check` の subtest を含む）で修正前に5失敗を再現し、修正後は plugin の5テストすべて成功。計画のコード例と不変条件も揃えた。

Minor の対応: 欠落 source とマウント先を作らないこと、親 `plugins` の symlink を `--check` で拒否すること、親が通常ファイルの場合の起動・診断の拒否を追加検査した。lint のコメント、opt-in しない利用者にもドリフト WARNING が出る旨、検証時点を明記した。

修正後の検証（この節を追加した commit のコードに対して実行）:

- `./lint.sh`: rc=0、警告ゼロ。
- `TMPDIR=/tmp ./test-build.sh --launcher-only`: rc=0、PASS=341 / FAIL=0。Codex launcher 38 tests を含む。
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_codex_launch.HostPluginsTests -v`: 5 tests、OK。
- Compose override と実マウントの定義は変更していないため、成功済みの実マウント83件とビルド17件は再実行していない。

保留した Minor:

1. source の symlink 実体に追加の範囲制限を設ける案（Claude M1）。ホストが管理する symlink を実体解決して共有する承認済み仕様を変更するため、今回は追加しない。別の rw 経路による変更・読み取り範囲の拡大まで本マウントが防ぐ保証はない。なお source が `/` なら `CODEX_DIR` との包含拒否で止まる。
2. 重なりと解決失敗のエラー文を分割する案（Claude M2）。いずれも拒否され、既存 fixture は解決可能なパスなので任意の診断改善として保留。

確認限定巡:

- Codex（gpt-6-astra、read-only、同じ session を resume、rc=0）: Yes。Important 1・Minor 1 は修正済み、Critical/Important の残存なし。確認対象は `df96db4` に対する未コミット差分で、その内容を変更せず `744b182` にコミットした（コミット準備時に sandbox の `.git` 制限があり、確認開始とコミットの順が入れ替わった）。
- Claude（claude-opus-5-5、同じ session を resume、`modelUsage` で確認、rc=0）: `744b182` のコードは Yes。Codex Important 1 と Claude M3〜M6 は修正・反映済み。Critical/Important の残存なし、保留の Minor 2件は上記のとおり。
- 初回結果は互いに共有せず取得した。確認限定巡では修正対象と生ログだけを渡し、全文レビューを繰り返していない。

両者とも A2〜A6 の未実施を機能全体の合格と扱っていない。対話受入が完了するまで PR 作成・マージへ進まない（A2〜A6 は上記のとおり 2026-09-25 に完了）。
リリース時の番号案は `v14.1.0`（新しい opt-in 設定キーの追加）。タグは作成していない。
