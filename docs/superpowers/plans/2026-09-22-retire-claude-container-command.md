# 旧コマンド `claude-container` の廃止計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

状態: 段階Aの実装・実機受入と初回の二重レビューは完了。PR #141 はドラフトで、後段レビューの警告漏れ修正に対する確認・CI 更新・公開が未完了。段階Bは起動方法の聞き取りまで、段階Cは未着手。日付による廃止期限は設けず、下記の移行・検証条件を満たした次のメジャー版で削除する。

目的: 起動本体を通常ファイルの `c3c` に移し、Claude Code と Codex を単一の入口から利用する。旧入口専用の引数解析・分岐を廃止する。

基点: `156f72cd8a67055c9cd97ab90679913809d3a9d1`。ローカルの直近タグは `v11.0.0`。作成時にあった README.md の変更、未追跡の調査文書・診断スクリプト・`__pycache__/` は本計画の変更ではない。

関連: [段階移行仕様](../specs/2026-09-20-c3c-incremental-design.md) 第2段階、[第2段階計画](2026-09-21-c3c-phase2.md)。旧入口を維持する従来の方針に対する後続計画であり、過去の検証記録を遡って書き換えない。

## 1. 対象と利用者向け契約

- 廃止するのは配布する旧実行ファイルと旧入口の動作。`c3c` は実行可能な通常ファイルになり、既存の c3c 引数仕様を維持する。
- `.claude-container.d/` の互換読込、`CLAUDE_CONTAINER_*`、state directory、Compose service・イメージ名・ラベル、認証・MCP 承認の保存先は維持する。これらの改名や削除は別変更とする。
- `c3c --agent claude|codex` も維持する。旧コマンドの削除に合わせたオプション整理はしない。
- `c3c` 無指定時の前回 CLI 選択・初回選択は維持する。旧コマンドの Claude 固定を引き継ぐ呼び出しは、必ず `c3c claude` に移す。

| 旧呼び出し | 移行後 |
|---|---|
| `claude-container <dir>` | `c3c claude <dir>` |
| `claude-container -b <dir>` | `c3c claude -b <dir>` |
| `claude-container --agent codex <dir>` | `c3c codex <dir>` |
| `claude-container --agent codex --read-only <dir>` | `c3c codex --read-only <dir>` |
| `claude-container --check [<dir>...]` | `c3c --check [<dir>...]` |
| `claude-container --agent codex --check <dir>` | `c3c codex --check <dir>` |
| `claude-container --clean [<dir>]` | `c3c --clean [<dir>]` |
| `claude-container --check --clean-missing` | `c3c --check --clean-missing` |

`claude` / `codex` という相対ディレクトリ名は `./claude` / `./codex` と明示する。先頭が `-` のパスには `--` を使う。新入口は通常起動のディレクトリを最大1件に制限し、未知オプションを拒否する。旧 parser の寛容さに依存するスクリプトも移行時に確認する。

## 2. 段階A: 互換版で廃止予告と事前診断を提供する

成果物は旧入口を残した独立 PR。削除 PR より先に利用可能にする。

- `claude-container` からの通常起動には stderr の `WARNING:` で廃止予定と移行例を表示する。既存の引数解釈、Claude 固定、記憶を読み書きしない動作、終了コードを保つ。help にも予告を載せる。
- `--check` に入口移行の診断を追加する。旧名で実行した場合は旧入口利用を警告し、対象プロジェクトの WARN に集計する。対象0件でも入口警告を表示する。既存の「WARN のみなら成功、FAIL なら失敗」の規則を保つ。
- 旧入口の `--check` は直接利用を WARN で知らせ、`c3c --check` は INFO で外部スクリプト・alias の利用状況が未確認であることを知らせる。警告が出ないことを全利用側の移行完了とは扱わない。
- 外部の shell 設定や cron を自動走査・実行する仕組みは作らない。`--check` は呼び出し元の旧名利用を診断できるが、任意の外部スクリプトの将来の呼び出しまでは検出できない。その限界と手動棚卸しを README に記す。
- README の主要な起動・導入例を `c3c` に更新し、上の移行表・廃止条件を追加する。従来の Claude 固定の例には `claude` を明示する。

主な変更: `claude-container`、`tests/test_c3c_launch.py`、README.md、`docs/development-invariants.md`。既存の `test-build.sh --launcher-only` から追加テストが実行されるため、同スクリプト自体の変更は不要。実装前に [開発不変条件](../../development-invariants.md) の launcher・check・選択記憶の節を読む。

受入: 通常起動・help・check、対象0件・複数件・FAIL併存で警告と終了コードを確認。check が設定・台帳・選択記憶・承認記録を書き換えず、CLI やコンテナを起動しないことを確認する。実ホストで旧入口の `--check` が移行対象を警告することを記録する。

## 3. 段階B: 利用側の起動経路を移行する

段階Aの互換版を使い、削除前に実施する。利用側の変更は対象と権限を確認してから行い、今回の計画作成依頼をホスト設定変更の承認とは扱わない。

1. 管理している利用プロジェクトと起動経路を棚卸しする。PATH 上の symlink、shell alias/function、ラッパー、Makefile、CI、cron・サービス、運用文書が対象。公開計画に個人の絶対パスや秘密は記録しない。確認結果は非公開の運用記録に残す。
2. 新しい PATH 入口を checkout の `c3c` に向ける。checkout ディレクトリ自体は改名しない。既存ファイルを無条件に上書きせず、元の symlink 先・定義を記録する。
3. 呼び出しを移行表に従って更新する。Claude 固定の wrapper と非対話実行は `c3c claude` と明示し、前回 Codex の記憶がある場合にも Claude を選ぶことを確認する。
4. 各利用プロジェクトで `c3c --check`、必要なら `c3c codex --check`、両 CLI の通常起動・終了・再開を確認する。Codex opt-out のプロジェクトでは意図した拒否を確認し、導入を強制しない。
5. 利用中のセッションを終了してから最終的な入口切替を行う。旧コマンドへの参照が残る経路は移行完了にしない。

完了条件: 管理対象の一覧に未確認・未移行がなく、実機結果と戻し方を記録したこと。第三者利用者の完全な棚卸しはできないため、互換版の README・リリース告知で破壊的変更と手順を公開してから削除版へ進む。固定の待機日数は設定しない。

## 4. 段階C: 次のメジャー版で本体を移し旧入口を削除する

成果物は段階Aとは別 PR。段階Bの完了をマージ・公開の前提にする。

1. symlink の `c3c` を通常ファイルに置き換え、旧 `claude-container` の本体をそこへ移す。実行属性を保つ。旧パスには wrapper も symlink も残さない。
2. `INVOKED_NAME` / `C3C_INTERFACE` による旧 parser・旧 usage・選択記憶の分岐を整理し、常に現行 c3c の契約を適用する。旧名の外部 symlink を新本体へ向けても旧動作が復活する仕組みは残さない。
3. `resolve_launcher_path()` の外部 symlink・相対 symlink 解決は維持する。入口の basename によって別 parser を選ばない。ヘルパー・Compose・ビルドアセットは従来どおり本体の実ディレクトリから解決する。
4. `rg` で追跡ファイルの旧名参照を列挙し、実行パス・関数抽出元・コピー元を個別に更新する。対象は `test-build.sh`、`lint.sh`、`tests/test_c3c_launch.py`、`test_c3c_config.py`、`test_codex_launch.py`、`test_agent_preference.py`、`test_project_images.py`、`test_network_timeouts.py`、`test_codex_entrypoint.py`、`test-lint-compose-checks.sh`、CI の該当参照。文字列の一括置換はしない。
5. 旧入口専用テストは廃止後の契約へ更新する。ガード・認証・MCP・ネットワーク・check の既存テストは新入口から継続し、旧入口削除を理由に安全性の検査を削らない。旧設定名を使う fixture は互換読込の検査として維持する。
6. README・AGENTS.md・開発不変条件・現行運用文書の本体パスと契約を同じコミットで更新する。既存の調査・実測記録、upstream 帰属、Issue URL、内部識別子は維持する。段階Aの予告は廃止済みの移行案内へ更新する。

## 5. 検証と公開条件

段階A・Cそれぞれで以下を実施する。

- `./lint.sh` と `TMPDIR=/tmp ./test-build.sh --launcher-only`。追加の同一テスト重複実行は不要。
- Compose 検証をコンテナ制約でスキップした場合は `not run` と記録し、実行可能なホストまたは CI で補う。警告や失敗を成功扱いにしない。
- 実 Podman ホストで `c3c claude` / `c3c codex` の起動と正常・異常終了、前回選択、CLI 明示、既存イメージ・設定・承認の再利用を確認する。CLI の終了コードが選択保存で上書きされないことは自動テストでも確認する。

段階Cではさらに以下を確認する。

- 配布ツリーの `c3c` が実行可能な通常ファイルで、旧パスが存在しない。実ファイル直呼び・PATH 経由・多段 symlink 経由でヘルパーと Compose が正しく解決される。
- 初回選択、非 TTY で CLI 無指定の拒否、EOF・Ctrl-C、`--`、不正引数、`--agent` とサブコマンドの重複拒否、check/clean の無選択・記憶無変更を維持する。
- ホストで `./test-build.sh --config-ro-only` を実行する。本体参照を変えたテストが、実ランチャーの準備処理と実 Compose の保護を引き続き検査できることを確認する。
- 本体移動だけでビルド入力・asset hash が変わらず、不必要な再ビルド・再承認を要求しないことを検査する。Dockerfile・entrypoint・ビルド入力まで変更が必要になった場合は範囲を見直し、README が要求する全体ビルド・実機再ビルドを追加する。
- 段階Aの実機 `--check` 記録、利用側の移行記録、必須 CI・レビューの完了を確認してから公開へ進む。未実行の必須検証がある状態を完了とは扱わない。

バージョン案: 直近タグが引き続き `v11.0.0` なら、予告・診断追加は `v11.1.0`、旧入口削除は `v12.0.0`。実装時に最新タグと変更全体を再確認する。削除は利用側の呼び出し変更が必要なため MAJOR。コミット完了後に番号と根拠を添えてタグを提案し、承認後に作成する。今回の計画では commit・push・PR・タグ作成を行わない。

## 6. 切り戻し

移行前に互換版の正確なタグまたは commit と、利用側の入口・wrapper の元定義を記録する。問題があれば稼働セッションを終了し、互換版の別 checkout へ入口を戻す。進行中の作業を `git reset --hard` で破棄しない。

新しい呼び出し `c3c claude` / `c3c codex` は段階Aの互換版でも使えるため、基本は製品 checkout の切替だけで戻せる。旧入口を必要とする経路だけ元定義へ戻す。設定・state・認証・承認の形式は変えないため、それらの一括復元や削除は行わない。戻した版で `--check` と通常起動を確認し、失敗した場合は記録して削除版の公開を止める。

## 7. 2026-09-22 の実装・検証記録

- 段階A: 旧入口の通常起動・清掃・help に廃止予告を追加。check は対象ごとに WARN 集計し、対象0件でも予告を出す。c3c の check には外部呼び出し経路を検査していない旨を表示する。旧 parser・選択記憶の扱い・終了コードは維持した。
- README の主要な起動例と移行表を更新。既存の別件 README 差分は保持した。
- `TMPDIR=/tmp ./test-build.sh --launcher-only`: sandbox 外で終了コード0、PASS=253 / FAIL=0。c3c suite は追加4件を含む42件成功。通常起動の Claude 固定・失敗コード保持、check の複数対象・対象0件・FAIL併存、HOME・対象プロジェクトの不変を検査した。
- 初回の sandbox 内実行は PASS=249 / FAIL=4。socket 作成拒否、`/proc` に依存する既存検査2件、新規テストの誤った期待値1件が失敗した。新規テストは HOME を診断対象にした既存の rw マウント警告を見落としていたため期待値を修正し、既存テストや製品の保護を緩めず、承認された sandbox 外の全体再実行で確認した。
- `./lint.sh`: 終了コード0、bash/shellcheck 成功。Podman 不在により Compose 検証は `not run`。実 Podman での旧入口 `--check` と両 CLI 起動も `not run`（このコンテナにホストの Podman がない）。段階Aの実機受入完了とは扱わない。
- 利用者から、普段は alias 経由で `c3c /path/to/repo` を呼ぶとの回答を得た。ホストの `type -a c3c` の出力で、alias が checkout 内の `c3c` を直接指すことを確認した。この alias は本体移動後も変更不要。実ファイルの状態・他の起動経路・実起動は未確認で、段階B完了とは扱わない。個人の絶対パスは本記録に掲載しない。
- commit・push・PR・タグ作成は未実施。旧本体の削除は実機受入と利用側確認後に進める。

## 8. 2026-09-22 のホスト継続検証

- 引き継ぎと照合し、HEAD は引き続き `156f72c`、段階Aと別件の未コミット差分が保持されていることを確認した。
- `./lint.sh`: sandbox 内では Podman の runtime directory が読み取り専用のため Compose 検証に失敗（終了コード1）。承認された sandbox 外で再実行し、Compose を含めて `lint OK`・終了コード0、警告なし。
- 本リポジトリを対象に、実 Podman ホストで旧入口 `--check`、`c3c --check`、`c3c codex --check` を実行。すべて終了コード0、各 `PASS: 0 / WARN: 1 / FAIL: 0`。旧入口だけに廃止予告が出ることを確認した。旧設定ディレクトリ・requirements のフォールバック、Codex の `latest` 指定による警告は残るため、WARN 数の差による判定はしていない。
- `c3c claude` は既存イメージで Claude Code 2.1.278 の対話画面と auto mode 表示まで到達し、`/exit` で終了コード0。コンテナ内 statusline に環境ラベルがないことも確認した（host 側の表示確認は未実施）。
- `c3c codex` は既存の MCP 承認（ローカル command 0件・ハッシュ一致）を再利用し、Codex 0.155.1 の対話画面まで到達。入力を取り消して Ctrl-D で終了コード0。PATH に bubblewrap がなく同梱版を使うという起動警告あり。sandbox 内のコマンド実行確認はしていない。
- 起動時に IPv6 sysctl への書込みが read-only となり、ip6tables DROP へフォールバックする旨の警告あり。起動時の許可先443・禁止先・ポート80の通信検査は成功。IPv6 境界自体の追加実測は未実施。
- 両 CLI の会話再開・異常終了・CLI 無指定での選択確認は `not run`（今回は明示CLIの起動・正常終了の確認まで）。全利用側の棚卸しも未完了。段階A・Bの受入全体を完了とは扱わない。
- 前回成功した launcher suite は製品・テストの変更がないため再実行していない。レビュー・commit・push・PR・タグ作成は引き続き未実施。

## 9. ホスト継続検証の追加結果

- `c3c <project>` の CLI 無指定起動で `INFO: 前回の選択: codex` を確認し、実 Codex の対話画面まで到達した。ランチャーは最終的に終了コード0。
- この検証用 Codex への SIGTERM による異常終了試験を試みたが、送信時にはコンテナが削除済みで Podman は終了コード255。ランチャーの異常終了伝播は確認できていない。終了の契機は未特定であり、正常終了操作の試験にも数えない。選択記録の内容は試験前後で一致した。
- ホストの alias 定義ファイルでも `c3c` が checkout の `c3c` を直接指すことを確認した。起動台帳の存在を確認したが、各対象の全呼び出し経路・cron・サービスまで棚卸ししたものではない。会話再開と全利用側の受入は引き続き未実施。
- 段階Aのコミット候補は `claude-container`、`tests/test_c3c_launch.py`、README の入口移行に関する差分、本計画の4ファイル。README の proc 障害調査段落と別件の未追跡ファイルは含めない。

## 10. 段階Aのレビュー対応

- `917c304` に段階Aの4ファイルをコミット。独立した読み取り専用の Opus 5 レビューは `156f72c..917c304` に対して実施し、Critical 0 / Important 0 / Minor 7、判定は With fixes（Minor のみ）。
- Minor 1・2・3・5・6を反映。ガードの位置づけ、help と README の旧入口との差、対象0件時の出力先・集計、テストの役割分担、残存するリビルド・清掃例を補正した。計画の診断説明と変更ファイル列挙も実装に合わせた。
- Minor 4（check の警告 prefix 統一）は未対応。既存の警告にも両形式があり、今回の入口警告の検出・集計はテストで確認済み。prefix の統一は警告全体の出力契約として別途扱う。
- Minor 7（台帳空の `--check --clean-missing` で予告が重複しうる）は未対応。ドライバの初期対象0件時にも知らせる現在の実装を保持する。重複表示だけで集計・清掃対象・終了コードへの影響はなく、制御フロー変更は今回の文書補正に含めない。
- 追加検証: `--validator-only` は PASS=82 / FAIL=0、承認ガードの回帰テストは全ケース成功。レビュー後の変更は文言・文書・コメントのみ。
- レビュー対応後の検証: `./lint.sh` は Compose を含め終了コード0・警告なし。`test_c3c_launch.py` は42件成功。新たな挙動変更はなく、help の文言・文書・コメントの補正に対する確認として実行した。

## 11. PR #141 後段レビューと追加受入

- ドラフト PR #141 の head `65c87cc` に対し、Codex（read-only）を先に起動し、新規 Fable 5.1 セッションで先行指摘の反映・未確認範囲・GitHub の状態を確認した。Fable は必須 CI 全成功と既存 Minor の対応を確認。Codex は `--check --clean-missing` の対象再構成で全件欠落となった場合の廃止警告漏れを should-fix として指摘した。
- 台帳経由と引数指定の両方で、旧入口の警告件数が0になることを新しい回帰テストで再現（c3c 側は警告なしを維持）。対象0件の判定を清掃診断による対象再構成後へ移し、同じテストが成功することを確認した。HOME・プロジェクトの内容不変とコンテナ無起動も検査する。この修正で先行 Minor 7 の重複表示も解消するため、同指摘は保留から対応済みへ変更する。
- 修正後の `./lint.sh` は Compose を含め終了コード0・警告なし。`TMPDIR=/tmp ./test-build.sh --launcher-only` は PASS=253 / FAIL=0。ケース数はテスト群単位の集計で、追加した Python テスト1件もこの実行に含む。
- 実機異常終了: 専用 PTY で今回の検証用コンテナを識別し、Claude は SIGTERM 後にランチャー rc143、Codex は SIGKILL 後に rc137 を確認。両方とも選択記録の内容は不変で、検証用コンテナが終了時に削除されることを確認した。Codex の SIGTERM 試行は rc0 だったため異常終了の実証には数えない。Codex への信号送信用 `podman exec` はコンテナ削除との競合で rc255 となるため、本起動の終了コードと分けて記録する。
- Claude の実機会話再開: 専用の短いテスト会話を名前付きで保存し、c3c でコンテナを起動し直してその会話だけを再開。前の識別子を復元でき、正常終了 rc0 を確認した。
- Codex の実機会話再開も同じ手順で成功。コンテナ再起動後に試験用の名前付き会話から識別子を復元し、正常終了 rc0 を確認した。これにより本リポジトリでの両 CLI の起動・正常終了・異常終了・会話再開と選択記憶の受入を確認。全利用側の経路棚卸しは段階Bとして残る。
