# CODEX_HOST_PLUGINS の検証記録

2026-09-24。対象: `41be0ff`（launcher）・`0e03e48`（Compose 検査）・`3fa0903`（文書）。
実装計画は [2026-09-24-codex-host-plugins.md](2026-09-24-codex-host-plugins.md)。

Task 1〜3 と受入前の指紋取得・A1 を実施した。A2〜A6 は計画の担当分担により、持ち主か Claude の対話セッションへ引き継ぐ。機能全体の対話受入は未完了。

## 自動検証

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

## 残る対話受入

| 項目 | 状態・理由 |
| --- | --- |
| A2: host/container の skill 名集合一致 | not run。計画上、対話コンテナを起動する担当へ引き継ぐ |
| A3: TUI 起動と自動 marketplace 更新のログ確認 | not run。対話担当の実画面・ログ確認が必要。起動を妨げる場合は計画へ戻す |
| A4: 実キャッシュへの書込み・upgrade 拒否、受入後の指紋・所有者確認 | not run。実キャッシュを使った対話受入の担当へ引き継ぐ |
| A5: Claude 経路での skill 読込み | not run。Claude の対話起動が必要 |
| A6: 有効化の設定を残したまま共有を無効化した起動 | not run。起動可否・警告・自動 install・書込みの観測を対話担当へ引き継ぐ |

次の担当は計画 Task 4 の A2〜A6 を実行し、README の A6 未確認表記と本記録を更新する。PR 作成・マージ・タグ作成は未実施。
