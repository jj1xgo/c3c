# c3c 第0B-4段階: 専用保存先へのChatGPT新規ログイン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 利用者が選択したChatGPT契約枠で、新しいコンテナ専用認証を作り、通常初期化後のdevice loginと安全な保存を確認する。

**Architecture:** 0B-2と同じ既存image＋main entrypoint readonly指定で通常firewallを初期化する。最後のClaude呼出しを、認証専用のreadonly shimへ渡す。専用CODEX_HOMEをrw mountし、新規認証だけを書き込む。認証・設定の共有を試す段階ではない。

**Tech Stack:** Linux/rootless Podman、podman-compose、codex-cli 0.155.1、Python3/PyYAML。

**Spec:** c3c incremental design G3/G4・第1段階。利用者は本セッションで「ChatGPTの契約枠で、新しくログインする」を選択済み。

## Global Constraints

- ホストのauth.json、keyring、実設定、vault、実プロジェクトを読まない・コピーしない・マウントしない。実Claudeも起動しない。
- 認証先は新規 `/tmp/c3c-login.*` 配下の0700専用home。`cli_auth_credentials_store="file"` を明示、umask077。通常ファイル・所有者・他者に読めないmodeだけを確認し、auth.json本文は出力も採取もしない。
- 認証homeはログ・アーカイブから分離し、recursive copyしない。成功後は次の実認証検査に引き継ぐため保持する。OSの一時領域なので長期保管先とは扱わない。logout・失効・削除は今回自動で行わない。
- image `28b724cd6363a9bdbc4f0a44386bdd6b7dc18d0c8fd7142ca219a83c277cc05c` を保持しbuild/pullなし。main entrypoint SHAを固定し0755コピーをreadonly指定。bakedのままのmain imageの検査ではない。
- 製品ENTRYPOINT/CMD配列、既定NET_ADMIN/NET_RAW、IPv4設定、firewallを維持。新しいcapability・privileged・seccomp緩和・firewall無効化なし。
- CLIは `codex -c 'cli_auth_credentials_store="file"' login --device-auth` と成功後の `login status` だけ。モデル実行・MCP・hook・refresh強制・料金が別になるAPIキーへの自動切替を行わない。
- CLIが提示する公式ログインURLと一時コードだけを利用者に案内する。ブラウザでの本人操作は利用者が行い、秘密の貼付けを求めない。期限切れは記録し、勝手に反復ログインしない。
- デバイス認証は最大900秒。終了・失敗後はowner/project labelで対象を確認して専用コンテナ/networkのみ清掃し、認証homeは保持。起動失敗時も同じ限定清掃を試みる。
- 製品コード変更・commit・push・PRは行わない。

## Review Focus

1. トークンの露出: auth本文を読まず、ログへ保存するのはCLIの端末出力だけ。auth homeを証跡へコピーしない。
2. ホストとの混同: envを限定、空env-file、解決済みmountの実パス検査。root fixture外は/dev/nullとreadonly/etc/localtimeのみ。
3. 境界を通らない認証: 通常ENTRYPOINT/CMDとfirewall初期化を経由し、ログのC3C_DEVICE_LOGIN_STARTを確認。
4. 不成立の誤判定: URL/コード表示は開始だけ。終了rc0、C3C_DEVICE_LOGIN_COMPLETE、login status、authの通常ファイルとmodeを揃えて成立とする。
5. 待機と失敗: 900秒timeout、起動失敗のcleanup、再試行禁止。待機中はブラウザ操作を明示して利用者へ返す。

## 添付・手順

添付は `/tmp/c3c-phase0b4/{start.py,manage.py,process_runner.py}`。実行には添付も必要。停止moduleは0B-2と同一。

### Task 1: 準備とレビュー

- [x] `python3 -m py_compile /tmp/c3c-phase0b4/start.py /tmp/c3c-phase0b4/manage.py /tmp/c3c-phase0b4/process_runner.py`。Expected: rc0。
- [x] セルフレビューとCodex独立レビュー。Critical/Importantを解消し確認限定巡。最大5巡、同型2巡で収束診断。
- [x] `./lint.sh`。Expected: rc0、Compose検証含む。Podmanに届くホスト実行を使う。

### Task 2: 認証開始と利用者操作

- [x] `python3 /tmp/c3c-phase0b4/start.py`。Expected: 専用ROOT/state生成、設定/権限検査を通り、detached専用コンテナ起動。host Podmanへアクセスするsandboxと、製品firewall経由の認証通信が必要。
- [x] `python3 /tmp/c3c-phase0b4/manage.py status`。Expected: 対象owner確認、CLI端末出力をprivate login-output.logへ保存。authは存在/modeのみ記録。
- [x] private端末出力で提示URLがOpenAIのHTTPSであることを確認し、利用者へURLと一時コードを案内。認証成功とはまだ報告しない。利用者によるブラウザ操作を待つ。

### Task 3: 認証結果と清掃

- [x] 利用者操作後に同じstatusコマンド。Expected: container exited rc0、C3C_DEVICE_LOGIN_COMPLETE、ChatGPTログイン状態、auth通常ファイル・所有者一致・modeにgroup/other権限なし。
- [x] `python3 /tmp/c3c-phase0b4/manage.py cleanup`。Expected: ownerコンテナと専用networkだけを削除し残留ゼロ、認証home保持。失敗/期限切れも同じ清掃、成立にはしない。
- [x] 結果文書に開始/成立/未完了を区別。認証home実パス・一時コードは公開文書へ載せず、stateはprivateのまま。schema/cwd検査と実認証の結論を合算しない。
- [x] 最終結果を独立レビューし、lintと残留確認を記録する。利用者待機中は未完了の台帳を保持し、実行中コンテナと期限を伝える。

## 適用と引渡し

Superpowers writing-plans / executing-plans / requesting-code-review / verification-before-completionを使う。既存の継続・認証方式の選択を再承認させず進めるが、本人のブラウザ操作は代行しない。

`/goal`文面: 「0B-4の専用ChatGPT device loginを開始し、利用者の本人操作後に成立確認・限定清掃・証跡レビューを行う。auth本文を読まずコピーせず、モデル実行へ進まない。」現セッションでは新規goalを作成しない。

[公式Authentication](https://learn.chatgpt.com/docs/auth)のdevice codeとfile保存を参照。CLI引数は0B-3の対象版helpで確認済み。

実装: Codex — ユーザーのCodex限定指示と、ChatGPT契約枠での新規認証の選択に従う。

## 実行前レビュー記録

初回C0/I2/M0。ホスト側umask077・保存dir0700・既存ファイル0600と所有者/非symlink検査を追加。ログ/認証metadata検査の失敗は記録し、owner確認済みの清掃を継続するよう修正。模擬3例（ログ失敗・認証mode失敗・正常）で清掃到達と保存権限を確認済み。確認限定巡C0/I0/M0。実行結果と清掃は [結果文書](2026-09-20-c3c-phase0b4-results.md) に記録。
