# c3c 第0B-1段階: 組み込み permission profile の追試結果

日付: 2026-09-20。対象 commit: `93211ed80ad3e4b4231f40ba5096df6924e76f34`。実行: Codex（持ち主の当面Codex限定指示に従う）。
計画: [第0B-1計画](2026-09-20-c3c-phase0b1-sandbox-validation.md)。前の観測: [第0A結果](2026-09-20-c3c-phase0a-results.md)。

## 結果

**組み込み profile を明示すれば、同じ既存コンテナイメージで内部コマンドが起動し、read-only の書込み拒否と workspace の書込み許可を観測できた。** 第0Aの `sandbox_mode` 指定だけの引数エラーとは異なる経路である。

| 条件 | 内部到達 | rc | OS・ファイルの観測 | 判定 |
|---|---|---|---|---|
| 素の Python 書込み対照 | `INNER_BEGIN` | 0 | `WRITE_OK`、`control.txt` あり | 成立 |
| `codex sandbox --permission-profile :read-only` | `INNER_BEGIN` | 42 | `OS_ERROR errno=30`（read-only filesystem）、`WRITE_DENIED`、`ro.txt` なし | 成立 |
| `codex sandbox --permission-profile :workspace` | `INNER_BEGIN` | 0 | `WRITE_OK`、`workspace.txt` あり | 成立 |

rc42 はプローブが EACCES/EROFS を受けた際に返す観測用コードであり、準備失敗ではない。全ケースで uid/gid=1000、cwd=`/workspace`。ファイル名はケース別とし、使い捨ての空 workspace 内で `open('x')` によって作成した。

## 条件と根拠

- image ID: `28b724cd6363a9bdbc4f0a44386bdd6b7dc18d0c8fd7142ca219a83c277cc05c`。第0Aと同一。静的検査で User=node、暗黙volumeなし、ENTRYPOINT完全一致。rootless=true。
- `codex-cli 0.155.1` と対象版 `sandbox --help` を再確認。前回のhelpと同じ `--permission-profile` を使い、`sandbox_mode` は指定していない。
- [公式 Permissions](https://learn.chatgpt.com/docs/permissions) にある組み込み値を採用。独自profile名や構文を推測していない。文書の内容は対象版での上記実測と区別する。
- 専用 Codex home は空から開始し、`config.toml` は空。ホストの実設定・認証を参照、共有、コピーしていない。
- 3ケースすべてに同じ workspace・probe・専用Codex home の3マウント。`--network none --pull never --userns=keep-id:uid=1000,gid=1000`。ENTRYPOINTは `setpriv --ambient-caps=-all --inh-caps=-all /usr/bin/tini --` を維持。
- 素の対照が成立した場合だけ、2つのprofileプローブを起動する。危険なfull-access、cap追加、seccomp緩和、firewall無効化、build/pullは行っていない。

根拠ログの正本は private 退避先 `$CC/.claude/test-results/<RUN_ID>/`。`RUN_ID=c3c-0a-811877-sd8rct`（前計画のhelperと互換の実験用prefixを使用。第0Aとは別領域）。公開文書へホストの実パスは転記しない。

| 主張 | 根拠 |
|---|---|
| image・rootless・対象版・起動条件 | `logs/image.json`、`rootless.log`、`profile-preflight.{log,rc,inspect}` |
| 3ケースのrc・内部到達・errno・uid | `logs/profile-control.*`、`profile-ro.*`、`profile-workspace.*` |
| 実行直後のファイル有無と分類 | `logs/profile-results.json`、生成元の `run.sh` |
| プローブの内容・設定 | `logs/write-check.py`、`config-used.toml` |
| 実行全体・準備・終了時の出力 | `run.log`、`run.rc`、`cleanup.log`、`cleanup.rc` |
| 後始末・削除後の確認 | `final-checks.json`、`cleanup-final.log` |

## 後始末と検証

- runner終了コード0、EXIT時cleanup終了コード0。台帳のコンテナは preflight と3ケースの合計4件。
- 実行完了後に全体stdout・runner・生成元・終了コードを退避し、コピー元とbyte一致を確認。保存後にも同じ8ファイルを再照合し、SHA256と一致結果を `archive-checks.json` に保存。削除手順の実体は `finalize.py` に保持。
- 対象labelの `podman ps` はrc0で空。image存在確認はrc0。
- 退避成功後に `cleanup --rm-root` を実行しrc0、ROOT不在を確認。既存image・worktreeは保持。
- 製品コードは変更していない。commit/pushなし。
- 静的検査: Bash構文、埋め込みPython 3ブロックの構文、repo `./lint.sh` 成功。最終実行はsandbox内のCompose検証が `/run/user` の書込み制限で失敗した（`lint-final.log`）。同じ検証をホスト権限で再実行し終了コード0・`lint OK`、Composeを含めて成功した（`lint-final-host.log`）。環境制約による失敗と成功を区別して記録する。
- 実行前の独立Codexレビュー: 修正必須の指摘なし。実測結果の独立Codexレビューも **Critical 0・Important 0・Minor 0**。通常entrypoint等の未実測を維持した限定的な結果として、次の計画へ渡せると判定。レビュー原文は `result-review1.md`。

## 次の段階へ渡す事実と、未検証の範囲

- 組み込みprofileの書式はこの版で成立し、コンテナ内で実際にOS書込み拒否まで到達した。第0Aの引数エラーで止まったままではない。
- **製品 `entrypoint.sh` は未通過**。同スクリプトが行うfirewall初期化・環境配線後の動作、モデル経由の強制力、旧 `codex exec --sandbox ...` と本追試の等価性は not run。
- ホスト側common-dirの明示採取、実認証・refresh、設定源別MCP承認、hook trust、会話内worktree移動・再開は引き続き not run。第0A 表Bを達成済みにしない。
- 製品の起動先は `entrypoint.sh:159` のClaude固定。既存 `tests/test-runtime.sh` のreadonly shim方式は通常entrypoint後の検証には使えるが、正式なCodex起動対応を実装したことにはならない。
- MCPゲートの対象は `entrypoint.sh:46–61` の `/workspace/.mcp.json`。Codex user TOMLを審査する機構があると仮定しない。
- 次の検証では、通常entrypointから続くプロセスツリーの動作を確認し、`podman exec` の結果で代用しない。実認証を扱う手順は認証保存先・mount範囲・通信先を具体化してから実行する。

本追試の成立は G3 完了・日常利用の安全性承認・製品実装許可を意味しない。
