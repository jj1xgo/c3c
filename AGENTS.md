# AGENTS.md

本ファイルは claude-container 自体を開発する AI エージェント（Claude Code・Codex 等）向けの開発ガイダンスであり、このコンテナを使って別プロジェクトを動かす利用者への指示ではない（利用側プロジェクトの使い方は README.md を参照）。

## プロジェクト概要

[sethjensen1/claude-container](https://github.com/sethjensen1/claude-container)（MIT）をフォークした Claude Code サンドボックス環境。apt/pip パッケージや Node.js バージョン等の設定は `.c3c/`（旧名 `.claude-container.d/` も移行期間中は読める）で利用側プロジェクトごとに指定でき、本リポジトリ自体は特定プロジェクトに依存しない。

claude-container は標準的な技術（Podman・iptables・fine-grained PAT 等）を取り入れつつ、使い易くて堅牢なコンテナ環境を目指す。新規の境界機構は標準技術の組み合わせを優先し、独自実装の追加は監査対象の拡大として避ける。

本リポジトリのミッションは「Claude Code を人手の確認プロンプトに頼らず走らせる（既定 `--permission-mode auto`、従来は `--dangerously-skip-permissions`）ための、プロジェクト非依存なサンドボックス境界の提供・維持」である。

## 開発の進め方

- 現在の README.md・`docs/` と実装の整合を優先する。挙動を変えたら README.md の該当節も同じコミットで更新する。
- シェルスクリプトは bash または POSIX sh で書き、shebang を明示する（`lint.sh` が shebang から dialect を自動判定するため）。セキュリティ境界に関わる制約（`source` しない設計、fail-closed、capability 剥奪、トークンの非 export、マウントの `:ro` 保護、入力検証、アセットのハッシュ照合、ファイアウォール生成のエラー処理 等）は `docs/development-invariants.md` に不変条件としてまとめてある。`c3c`・`agent-preference.py`・`project-images.py`・`compose.yml`・`Dockerfile.claude`・`entrypoint.sh`・`init-firewall.sh`・`ipv6-firewall.py`・`firewall-refresh.py`・`codex-mcp-audit.py`・`git-askpass.sh`・`validate-build-input.sh` を変更する前に該当節を読むこと。
- ファイルを編集したら、そのターン内で `./lint.sh` を実行し、原則として終了コード 0・警告ゼロを確認する。README.md が説明する環境制約で Compose 検証をスキップした場合は、理由とともにその検証を `not run` と報告し、lint 全項目の検証完了とは扱わない。残る必須検証は実行可能なホスト・CI 等で確認する。README.md「変更後の確認」節に、変更箇所ごとに追加で必要な検証（`test-build.sh` の各モード、実機リビルド等）が一覧されている。該当する検証を実行し、実行できなかった場合は理由とともに `not run` と明記する（実行済みの検証結果とテスト成功・環境制約による未実行は区別して報告する）。
- 日本語で書く（README.md「表記」節の既定の例外に従う。技術用語・コマンド名・URL・機械可読トークン等は英語のままでよい）。

## バグ修正

再現ログ・`./lint.sh`・`--check` の出力で裏取りしてから最小変更で直す。テストコマンドの一覧は README.md「変更後の確認」節を参照する。

## バージョン管理（SemVer タグ）

利用者から見えるインターフェース（CLI 引数・`.c3c/`（旧 `.claude-container.d/`）の設定形式・デフォルト挙動）が変わる一連の変更をコミットし終えたら、SemVer 判定に基づく番号案と根拠を添えてタグ付与を提案する（ユーザー承認後に作成、自動作成しない。内部品質・docs・hook 調整のみでは提案しない）。判定基準は README.md「バージョニング」節を参照する。利用側に移行作業が必要な変更は、タグ提案前に `--check` が当該変更を検出できることを実機確認する。

## 個人運用の補足

`.claude/AGENTS.md` が存在し、まだ読み込まれていなければ、個人の開発運用（issue 起票・レビュー・計画置き場・グローバル指示との関係等）の補足として一度読む。存在しない場合（本リポジトリの fresh clone 等）は本ファイルと README.md・`docs/` に従えばよい。`.claude/AGENTS.md` は本ファイルの共通制約を置き換えるものではない。
