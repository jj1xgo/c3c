# examples/hooks/

claude-container のプロダクト本体には配線されていない、任意採用の Claude Code hook 例です。
必要なプロジェクトの `.claude/settings.json` に自分で配線してください。

## block-pr-approve.sh

`gh` の PR 承認操作（`gh pr review --approve` / `-a`、および生 API 経由の `event=APPROVE`）だけを
ブロックし、`--comment` / `--request-changes` 等その他の PR 操作・gh コマンドは通す PreToolUse hook です。

**背景**: `SECRETS_DIR` 直下の `GITHUB_MAIN_PAT`（README.md「GitHub トークンの配線」節）が
`Pull requests: write` を持つ場合、PR レビュー承認（`GH_TOKEN=$(cat "$GITHUB_MAIN_PAT_FILE") gh pr
review --approve` 等）は `Contents: write` なしでも実行できます。対象リポジトリで auto-merge が
有効な状態だと、コンテナ内トークンによる承認だけで required review 条件が満たされ GitHub 側が自動
マージしてしまう可能性があります（詳細は README.md「セキュリティモデル」節）。auto-merge を無効に
保つことが1枚目の壁で、このhookはその2枚目の壁として、Claude自身のうっかり自律承認を機構的に防ぎます。

脅威モデルは「Claude 自身のうっかり自律承認の抑止」であり、変数展開・コマンド置換等による意図的な
難読化までは防げません（公式もコマンド文字列パターンは fragile と明記）。誤検知は必ず安全方向
（承認をブロックする側）へ倒す設計です。実装の詳細な設計判断はスクリプト本体のコメントを参照してください。

`--approve=true` / `-a=1` などの値付き承認フラグも拒否します。引用部分を除去した文字列では
値を厳密に評価できないため、`--approve=false` / `-a=false` や不正値も安全側に拒否します。
コメント・変更要求を行うときは、偽値を指定する代わりに承認フラグ自体を省いてください。

バッククォート直前の承認フラグも終端として認識し、次の単純な形は拒否します。

```sh
x=`gh pr review 1 --approve`
```

これはコマンド置換全般の解析ではありません。通常経路では単一引用文と heredoc 本文
（区切り語の引用有無を問わず）は検査対象から除去されます。引用しない区切り語の heredoc
では本文のコマンド置換が実行されますが、検出できません。通常経路ではダブルクォート内の
コマンド置換も引用符除去で消えるため、検出できません。jq 不在時は引用文・heredoc 本文を除去できず、上の例を
引用しただけの場合も安全側に拒否します。

### 配線方法

対象プロジェクトの `.claude/settings.json` に以下を追加します（`claude-container` を使わずホスト直接
実行の場合も同様）:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "bash \"$CLAUDE_PROJECT_DIR/examples/hooks/block-pr-approve.sh\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

`block-pr-approve.sh` をプロジェクトの `.claude/hooks/` 配下などにコピーして配置する場合は、
`command` のパスをコピー先に合わせてください。

### テスト

回帰テストは `tests/test-block-pr-approve.sh` に同梱しています。トリガー文字列
（`gh pr review --approve` 等）をコマンド履歴に平文で残さないよう、実行は以下の1コマンドで完結させてください:

```bash
bash examples/hooks/tests/test-block-pr-approve.sh
```
