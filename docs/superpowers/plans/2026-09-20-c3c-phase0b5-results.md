# c3c 第0B-5段階: モデル経由worktree移動の結果

日付: 2026-09-20。source commit `93211ed80ad3e4b4231f40ba5096df6924e76f34`、codex-cli 0.155.1。
計画: [0B-5計画](2026-09-20-c3c-phase0b5-model-validation.md)。実行・レビューはCodex。

## 結果

**標準App Server経由で、同じthreadの作業先をA→B→Aと移し、各場所でモデルがツールを実行できた。** 指定モデルとthread metadataは `gpt-6-astra`。ChatGPT専用認証を使用し、provider fallbackは許可していない。

| 観測 | A（第1ターン） | B（第2ターン） | A（第3ターン） |
|---|---|---|---|
| ツールで取得したcwd | `/workspace/worktrees/a` | `/workspace/worktrees/b` | `/workspace/worktrees/a` |
| marker.txt読取 | WORKTREE_A | WORKTREE_B | WORKTREE_A |
| 相対attempt.txt書込 | Errno30、exit1 | Errno30、exit1 | Errno30、exit1 |
| AGENTS.mdにある応答末尾 | TAG_A | TAG_B | TAG_A |
| 第1ターンだけで与えた会話token | 提示した | ORCHIDを回答 | ORCHIDを回答 |

3ターンのthread IDは同一。各raw callは、要求したPythonコマンドと完全一致する単一execで、workdir指定・cd・権限昇格はなかった。call_id一致の出力にcwd、marker、WRITE_ATTEMPT、OSのread-onlyエラーを確認。各ターン後と終了時にA/Bのattempt.txtは不在だった。事前の非sandbox書込対照は両worktreeで成功し、対照ファイルを削除してからモデルを起動した。

AGENTSのtagはプロンプトに正解値を含めず、モデルの明示的なAGENTS読取コマンドもなかった。この条件で指示が移動先に追従した観測であり、任意のskill・MCP・hook・全設定の再読込を証明するものではない。

## 設定比較は未成立

**project設定medium/highの実効比較はnot run（プローブのtrust指定不備）。** CLIの `-c` キー組立でパスに含めた引用符がキーの一部になり、config/readのprojectsキーには引用符付きの文字列が記録された。A/Bのproject layerは両方disabledReason付き、実効model_reasoning_effortはnullだった。0B-3の信頼済みconfig/read結果とは条件が異なる。

この結果を「設定が共通化された」「設定値が追従した」と扱わない。モデル呼出しの追加再試行は行わず、正しいtrust指定を無認証で検証してから、必要な設定追従テストを別途行う。認証や保護を緩めて対処しない。

## metadataと実効cwdの差

Bへsettings/update直後のthread/readは、`thread.environments[0].cwd=B` に対し、トップレベル `thread.cwd=A` だった。Aへ戻した直後も environmentsはA、トップレベルcwdはBだった。実ツールのcwdは新しい場所へ追従した。今回の順序ではトップレベルcwdだけを現在の実行先の正本にできない。

## 初回停止と修正後の実測

初回はAのモデルターンとOS拒否まで成立したが、commandExecutionイベントを期待したプローブが、実際のcustom_tool_call/exec形式を扱えず停止した（container/runner rc1）。その証跡を保持し、成功runとして上書きしていない。

実ログのcall_idと出力から原因を特定し、既知の単一exec形式を静的に読む検証器へ修正した。モデル由来JavaScriptを実行せず、未知ツール・追加ツール・workdir指定・出力不一致は拒否する。実ログ再生と11改変ケース、計12件を確認。修正の独立レビュー後、一度だけ新規fixture/threadで3ターンを実測した。上表はこの修正版だけの結果であり、初回と同じ会話ではない。

修正版は3ターン完了、完了マーカー、server rc0、container rc0、runner rc0。両実行ともownerコンテナ/network削除rc0、残留一覧空、image保持。認証homeを保持し、認証ファイルは通常ファイル・所有者一致・0600のまま。本文を読まずコピーしていない。

## 証跡とレビュー

private実行領域の初回・修正版それぞれに、実行添付、probe-output.log/stderr、inspect、state、清掃ログを保持。修正版summary.jsonは抽出補助であり、生ログが正本。認証homeは証跡のコピー対象外。regular証跡114ファイルを `$CC/.claude/test-results/c3c-0b5-model-validation/{initial,revised}/` へ退避し、全件SHA-256一致を確認した。退避先はdir0700・files0600。

計画レビューは初回C0/I3/M1→確認C0/I0/M0。実ログ対応修正はC0/I1/M0→確認C0/I0/M0。構文確認、模擬失敗6ケース、実ログ検証12ケース、実行前ホストlintは成功。最終結果レビューはC0/I0/M0。補助ファイル2件のmode不一致は0600へ是正して確認済み。編集後のホスト `./lint.sh` はComposeを含めrc0、警告ゼロ。

## 残る検証

標準CLI/TUI内での作業先変更、AIが自分で次のworktreeを選ぶ入口、worktree自動作成、MCP/hook定義変更と再承認、書込可能モードでの移動、コンテナ再起動後の会話再開、G4の設定共有解消は **not run**。App Server実測をc3c製品機能の完成と扱わない。今回のreadonly拒否は3つの固定コマンドに対する観測であり、sandbox全経路の証明ではない。
