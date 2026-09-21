# c3c GitHub 改名の検証記録

2026-09-21、[第2段階計画](2026-09-21-c3c-phase2.md) の Task 5 に従い、持ち主の明示承認後に同じ GitHub リポジトリを `jj1xgo/claude-container` から [jj1xgo/c3c](https://github.com/jj1xgo/c3c) へ改名した。基点と改名後の main はともに `2c361f863a1116928b0539f3d7759c4955232f21`。

## 操作と照合

| 項目 | 結果 |
|---|---|
| 新名の事前確認 | 新名の API は 404、所有者で認証した取得可能な所有リポジトリ一覧にも該当なし。改名操作の成功で利用可を確定 |
| 改名 | `gh repo rename c3c --repo jj1xgo/claude-container --yes` 成功 |
| Repository ID | 改名前後とも `1218865682` |
| 公開設定 | public、default branch は main、auto-merge 無効、Pages 無効を保持 |
| 保護設定 | rulesets は空、main の branch protection は URL 以外すべて一致。必須チェック 4 件を保持 |
| Git refs | API で取得した refs と参照先が URL 以外すべて一致 |
| Issue / PR | 全125件の ID・番号・open/closed 状態・Issue/PR 区分が一致。open Issue 9件、open PR 0件 |
| ローカル origin | `https://github.com/jj1xgo/c3c.git` に更新し、`git fetch origin` 成功。HEAD と origin/main が基点 SHA に一致 |
| 旧 URL | GitHub API が新名と同じ Repository ID を返すことを確認 |
| v10.0.0 | annotated tag の参照先が基点 SHA と一致。Release は draft=false・prerelease=false のまま |
| CI | 改名後に `gh pr checks 136 --repo jj1xgo/c3c` で既存の必須 4 件の pass を確認。新しい実行の成功を意味しない |
| 起動経路 | 既存の起動用 symlink の参照先を確認。ホストの checkout ディレクトリは改名していない。PATH 上の c3c symlink の追加は未実施 |

最初の sandbox 内からの API 取得・改名はネットワーク制約で失敗したため、承認された権限昇格で再実行した。origin 更新も `.git/config` の読み取り専用制約により最初は失敗し、承認された権限昇格後に成功した。失敗した試行は成功に数えていない。

## 文書・依存参照の確認

- README の公開名、現在の取得先、Release コマンドと Releases リンクを新名へ更新した。
- `docs/runtime-ci.md` の手動実行・照会・ログ取得コマンドの `-R` を新名へ更新した。
- upstream の帰属、過去の Issue/PR・実行ログの URL、内部識別子は維持する。
- `.github/` の workflow に自リポジトリの旧名を固定した参照はない。追跡対象の `action.yml` / `action.yaml` はない。
- `.mcp.json.example` は GitHub MCP の汎用 endpoint を参照し、リポジトリ名を含まないため変更不要。
- 第2段階計画と第2b-2段階の結果記録に残っていた「PR・公開未実施」を、GitHub の現在状態と照合して更新した。

[GitHub の公式仕様](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository)では、Web と Git の旧 URL は転送されるが、Pages のプロジェクト URL と改名されたリポジトリが提供する Action の呼出しは例外になる。旧名を再利用すると転送が失われるため、旧名で新規リポジトリを作らない。

## PAT の対象設定

2026-09-21、持ち主が GitHub の設定画面で、コンテナ用の対象 fine-grained PAT すべての Repository access に `c3c` が含まれることを確認した。これは持ち主による設定確認であり、改名後のコンテナ内からの実操作検証ではない。公開リポジトリのメタデータ取得成功を PAT の対象設定の証拠にしていない。トークン値の取得・表示・複製、検証目的の Issue 投稿などは行っていない。

## 残る確認・not run

- 文書更新のレビュー・commit・push・PR と、その差分に対する CI は未実施。
- 文書更新後の `./lint.sh` は15本・警告0、Compose 検証込みで終了コード0。`git diff --check` も成功。テスト・実コンテナ起動の再実行は not run（変更は文書のみ）。
- 実在利用側の設定変更・再ビルドと、日常利用の受入は本作業に含めていない。

異常を検出した場合は新名で追加作業を進めず、旧名が利用可能かを照合して同じリポジトリを旧名へ戻し、origin も合わせて戻す。今回は保持確認に差異がなく、戻し操作は未実施。
