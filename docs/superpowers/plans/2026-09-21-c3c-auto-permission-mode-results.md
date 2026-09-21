# 結果: Claude 起動既定を `--permission-mode auto` にする（c3c）

計画: `2026-09-21-c3c-auto-permission-mode.md`。基点 main `6150cc5`、ブランチ `c3c/auto-permission-mode`。実施日 2026-09-21、実施者 Claude（Opus 5）。ホスト側パスは `<scratch>` 等に置き換えて記す。

## Task 1: 受理可否の計測

`./test-build.sh --build-only`（host、`localhost/claude-test`）: PASS=17 FAIL=0、`podman build --no-cache` と `claude --version` を含む。

```
$ podman run --rm localhost/claude-test claude --version
2.1.278 (Claude Code)
$ podman run --rm localhost/claude-test claude --help | grep -n -A3 -- '--permission-mode'
144:  --permission-mode <mode>              Permission mode to use for the session
145-                                        (choices: "acceptEdits", "auto",
146-                                        "bypassPermissions", "manual",
147-                                        "dontAsk", "plan")
```

`auto` が choices に含まれるため実装へ進んだ。この結果は「引数を受理する版」であることの根拠にとどめ、auto が有効かは下記の実モード表示で別に確認した。

公式 permission-modes 文書（https://code.claude.com/docs/en/permission-modes ）を 2026-09-21 に実装者自身が再確認した。要点: フラグ・設定・既定が `auto` を選んでも auto が利用できないセッションでは Manual（config 値 `default`）で開始する。利用不可の条件は `permissions.disableAutoMode`、非対応モデル、Anthropic のサーバー側での一時停止等。計画と README の文言はこれと一致する。

## 静的検証（host）

| 段階 | 結果 |
|---|---|
| `./lint.sh` | `lint OK`、exit 0、WARN 0 |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_codex_entrypoint.py -v` | 15 テスト OK（`test_default_and_explicit_claude_keep_existing_order_and_argv` が `claude --permission-mode auto` を確認） |
| `TMPDIR=/tmp ./test-build.sh --launcher-only` | PASS=253 FAIL=0 |
| `bash examples/hooks/tests/test-block-pr-approve.sh` | 全ケース green |
| `bash tests/test-runtime.sh --image localhost/claude-test`（本ブランチの entrypoint でビルド済みの test イメージ。`docs/runtime-ci.md` が起動処理の変更時に求める検証） | 終了コード 0。environment / mounts / control-before / protected / control-after PASS、build と IPv6 は not run（既存イメージ指定・IPv4 構成） |

## 旧イメージのドリフト検知（対照実験）

保守者の既存イメージは試行ブランチ（既に `--permission-mode auto`）でビルドされていたため「旧 entrypoint のイメージ」として使えなかった。使い捨てディレクトリ `<scratch>` を対象に、変更前の main `6150cc5` の launcher で `./c3c claude -b <scratch>` を実行し、旧 entrypoint（`exec claude --dangerously-skip-permissions`、イメージ内 `entrypoint.sh` 212 行目で確認）のイメージを作った。起動した Claude は Bypass Permissions の承諾画面で待機したため `podman stop` で止めた。

同じイメージに対する `--check`:

| launcher | 境界アセットの WARNING |
|---|---|
| main `6150cc5`（変更前） | 出ない（結果 WARN は `.c3c/` の欠落警告のみ） |
| 本ブランチ（変更後） | `WARNING: 境界アセット（entrypoint.sh・init-firewall.sh 等）がイメージのビルド後に変更されています。-b でのリビルドを推奨します。`（結果 WARN に集計） |

通常起動（`-b` なし）時の同じ WARNING は not run（`claude-container` の本起動経路も同じ `guard_asset_drift` を呼ぶことをコードで確認したのみ）。

WARNING の行に `[WARN]` 接頭辞は付かない（`guard_warn()` は素の `WARNING:` を stderr に出し、`--check` では集計フラグだけ立てる）。README「変更後の確認」の記述はこの実文言に合わせた。

## 再ビルドと実起動（実 argv・実モード）

本ブランチの launcher で `./c3c claude -b <scratch>`: build が run と別ステップで成功し、Claude Code が起動した（非ゼロ終了なし）。

実 argv（別シェルから）:

```
$ podman top <container> pid,args
1           /usr/bin/tini -- /usr/local/bin/entrypoint.sh
2           claude --permission-mode auto
$ podman exec <container> grep -n 'exec claude' /usr/local/bin/entrypoint.sh
217:  exec claude --permission-mode auto
```

実モード表示（起動ログの端末出力からエスケープ列を除去して抜粋）: `Claude Code v2.1.278`、`Fable 5.1`、`Claude Pro`、プロンプト下部に `auto mode on (shift+tab to cycle)`。従来の既定で出ていた `WARNING: Claude Code running in Bypass Permissions mode` の承諾画面は出ない。すなわち「引数が受理され、かつ auto mode が有効」で開始した（Manual への戻りは起きていない）。この表示は Claude Pro のアカウント・Fable 5.1 での結果であり、auto が利用できない条件（`disableAutoMode`、非対応モデル等）のセッションは未計測。

再ビルド後の `./c3c claude --check <scratch>`: 境界アセットの WARNING は消えた（残る WARN は `<scratch>/.c3c/` の欠落警告）。

## not run

- Codex 起動回帰（`./c3c codex <dir>`）: 使い捨て dir に `CODEX_DIR` の設定が無く未実施。Codex 経路の行は無変更で、単体テスト 15 件（Codex 経路の verify → exec を含む）は成功。
- MCP ゲート実機（stdio 型 `.mcp.json` で `n`）: 任意項目のため未実施。単体テストが同じ経路を検査済み。
- auto mode 下での Claude Code 本体の MCP 承認プロンプトの挙動: 未計測（README にもその旨を明記）。
- CI（PR の `ci.yml`）: PR 作成後に確認。
