# Codex の /proc マウント失敗（#140）

2026-09-22 の調査記録。対象は [#140](https://github.com/jj1xgo/c3c/issues/140)。製品の起動設定は未変更。システム版 bubblewrap の追加を戻して再ビルドした利用側から、通常起動と境界の受入完了が報告され、issue はクローズ済み（後述「利用側の受入結果」）。

## 確認できたこと

報告されたホスト比較では、bubblewrap 0.12.0 に `--proc /proc` を渡すと `Can't mount proc on /proc: Operation not permitted` で失敗し、Podman の `unmask=/proc/*` を追加すると成功する。ただし ENTRYPOINT を置き換えた比較であり、この比較単独では通常の c3c 起動経路の成功を確認していない。

別の原因候補として、Codex の失敗検出と bubblewrap のエラー表記の不一致を確認した。

- [Codex 0.155.1 の `run_bwrap_with_proc_fallback()` と `preflight_proc_mount_support()`](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/linux-sandbox/src/linux_run_main.rs) は、本コマンドの前に `/proc` の新規マウントを試す。認識できたマウント失敗なら `mount_proc=false` に切り替える。
- 同ファイルの `is_proc_mount_failure()` は、エラーに `Can't mount proc`、`/newroot/proc`、所定の権限エラー等が含まれることを要求する。報告の `/proc` はこの条件に一致しない。
- [bubblewrap 0.12.0 の `SETUP_MOUNT_PROC` 処理](https://github.com/containers/bubblewrap/blob/v0.12.0/bubblewrap.c) は、エラー表示に `op->dest` を使う。`--proc /proc` なら報告と同じ `/proc` になる。
- [Codex 0.155.1 の launcher](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/linux-sandbox/src/launcher.rs) は、必要な機能を持つシステム版 bwrap を同梱版より先に選ぶ。

ユーザーがホストで初版の診断スクリプトを実行した結果、実 Codex 0.155.1、システム bubblewrap 0.12.0 を確認した。Podman 5.8.6、カーネル 7.2.6-local。結果は次のとおり。

| 検査 | 終了コード・結果 |
| --- | --- |
| bwrap、新規 `/proc` あり | 1、`Can't mount proc on /proc: Operation not permitted` |
| bwrap、既存 `/proc` 継承 | 0、`OK` |
| Codex 診断呼出し（引数に誤り、下記参照） | 両方とも 1、同じマウントエラー |

CapInh/CapPrm/CapEff/CapAmb はゼロ、Seccomp=2。`/proc` 配下のマスクと読み取り専用マウントも採取できた。自動切替の失敗という仮説と整合するが、Codex が選択した実バイナリのトレースは未実施。

初版は `CODEX_HOME` を `/tmp` に置いたため helper alias 作成拒否の警告も出た。これは診断側の不備なので `/home/node` 配下へ修正した。マウントエラーとの因果を混同せず、修正版で再比較した（以下）。

### 第2回の比較と診断コマンドの訂正

同じイメージで system / bundled の比較をユーザーが実行した。helper alias の警告は解消。system は引き続き `/proc` マウントエラー（rc 1）、bundled は `Failed to execvp linux: No such file or directory`（rc 101）となった。

診断スクリプトの `codex sandbox linux -c ... -- ...` が誤りだった。0.155.1 の実機 `codex sandbox --help` と [CLI の `HostSandboxArgs` および `Subcommand::Sandbox` の実装](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/cli/src/main.rs) を確認したところ、OS 名のサブコマンドはなく、正しくは `codex sandbox -c ... -- ...`。`linux` は実行するコマンドとして扱われていた。このため、これまでの2回を read-only の `pwd` / workspace-write の `git status` の実行検証とは扱わず、指定したポリシーの適用確認も取り消す。

bundled の結果は exec 段階まで進んだことを示すが、目的のコマンドの成功ではない。スクリプトから `linux` を除き、実 argv をログに表示するようにした。修正した read-only の `pwd` は開発環境の Codex 0.155.1 で rc 0、`/workspace` の出力を確認した（二重サンドボックス内では内部ロックの書込みが失敗したため、承認済みの外側実行で確認）。この時点では対象ホストの同じイメージでの正しい呼出しの比較が残っていた。

### 第3回の比較（正しい CLI 呼出し）

ユーザーが同じイメージ（ID `5705bfe02f86ce01d31b5455d894f85b1e3f089286a6bcd248a704e039db06c5`）で訂正後のスクリプトを実行した。

| 実行 | システム版 0.12.0 | Codex 同梱版 |
| --- | --- | --- |
| `codex sandbox -c 'sandbox_mode="read-only"' -- /bin/pwd` | rc 1、`/proc` マウント失敗 | rc 0、診断リポジトリのパス |
| `codex sandbox -c 'sandbox_mode="workspace-write"' -- git status --short --branch` | rc 1、`/proc` マウント失敗 | rc 0、空の Git リポジトリの状態 |

両ケースの `/proc` マスク・読み取り専用マウント、Seccomp=2、CapInh/CapPrm/CapEff/CapAmb=0 は同じ。少なくともこの環境では、Podman の保護設定を緩めず同梱版で実行できることが確認できた。失敗判定の不一致というソース上の説明とも整合する。読み取り専用保護に対する書込み拒否や、製品の起動経路全体の受入はこの比較では検証していない。

同梱版の Git で `/root/.config/git/ignore` の Permission denied 警告が出た。診断用 root 初期化から uid 1000 へ移る際に HOME が残ったため、スクリプトに `HOME=/home/node` と `XDG_CONFIG_HOME=/home/node/.config` を明示した。この時点では警告修正後の実 Podman 再実行は未実施で、上表は修正前のユーザー実行結果である。公開前の再実行結果は末尾に記す。

## 利用側の受入結果

2026-09-22 の [findsummits 側の完了報告](https://github.com/jj1xgo/c3c/issues/140#issuecomment-5769730943)では、bubblewrap 追加を戻したコミット `9c1f89e` を再ビルドし、通常起動した別コンテナで次を確認した。これは上記の ENTRYPOINT を置き換えた比較とは別の、利用側セッションによる受入結果である。

- システム版 bwrap は未導入。同梱版は実行可能。
- 通常の Codex サンドボックス内で `pwd` と `git status` が rc 0。サンドボックス外への切替なし。
- `.gitconfig` と Codex MCP 承認ファイルの書込み用 open は EROFS、`/proc/sys/kernel/hostname` と `/proc/sysrq-trigger` は EACCES。書込み・truncate は実施していない。
- `/proc` のマスク・読み取り専用マウントを維持。非特権ユーザーの `iptables -S` / `ip6tables -S` は拒否。
- コンテナ側で確認した IPv4 HTTPS は、許可先2件に接続成功、禁止先2件に接続失敗。Codex 自身のネットワーク禁止をコンテナの拒否として数えていない。
- コンテナ側は CapInh/CapPrm/CapEff/CapAmb=0・Seccomp=2、Codex サンドボックス内は CapBnd を含め capability=0・Seccomp=2・NoNewPrivs=1。

再ビルドと通常起動はユーザー確認済み。この範囲で issue の受入条件を満たしてクローズした。IPv6 実通信と c3c 全体の回帰テストは、この利用側受入では **not run**。上記の結果をすべてのホスト・版に一般化しない。

## 対応方針

今回の利用側では、Codex のために追加したシステム版 bubblewrap を外し、同梱版を使う方針とし、上記の通常起動で受入を完了した。他のツールがシステム版へ依存していないかを確認したうえで、利用側の `.c3c/packages.txt` の追加行を戻し、`c3c codex -b <project>` で再ビルド・起動する。c3c 同梱の `packages.txt` と `Dockerfile.claude` は bubblewrap を明示追加していないため、本体でパッケージを一律削除する変更は不要。間接依存等でシステム版が残る場合は、依存関係を確認し、強制削除しない。

起動後は `command -v bwrap` でシステム版が残っていないこと、Codex の通常のサンドボックス付きコマンド実行で `pwd` / `git status` が成功することを確認する。今回の2ケース比較は成立したので、HOME 警告だけのために同じ診断を繰り返す必要はない。同様の環境へ適用する場合の受入は、製品の通常起動で行う。

上流の失敗検出修正も候補として残す。独自の stderr 書き換えラッパーや sandbox 無効化は導入しない。

`unmask=/proc/*` は解消条件として報告されているが、本件では既定へ追加しない。[Podman の仕様](https://docs.podman.io/en/v4.4/markdown/options/security-opt.html)では unmask は既定のマスクと読み取り専用保護に関わる設定であり、`/proc/sys` 等への影響も評価が必要。個別パスの最小化も未検証。既存 `/proc` を継承する方式も新規 PID namespace に対応する procfs とは異なるため、保護範囲が同じとは扱わない。

## ホストでの切り分け

Podman のあるホストで、問題が起きたローカルの c3c イメージを指定する。対象には Codex と `/usr/bin/bwrap` が導入されている必要がある。システム版を削除済みのイメージでは、比較用の移動元がないためこの診断は完走しない。

```bash
bash tests/diagnose-codex-proc.sh <ローカルイメージ>
```

この診断は既存イメージの ID を固定して使い捨てコンテナを起動する。pull・build、認証情報やプロジェクトのホストマウント、ネットワーク、unmask は使わない。Codex 用 home と Git リポジトリは使い捨てコンテナ内だけに作る。イメージ自体に秘密を焼き込んでいないことが前提。

修正版は2個の使い捨てコンテナで比較する。片方だけ `/usr/bin/bwrap` を別名へ移し、Codex の同梱版選択を検証する。移動は使い捨てコンテナの書込み層だけで行い、イメージ・既存コンテナ・ホストの bwrap は変更しない。両ケースとも root で準備後、`setpriv` で uid/gid 1000 と ambient/inheritable capability 剥奪を適用して診断する。これは診断の初期化経路であり、製品 ENTRYPOINT の代替検証ではない。

採取する内容は Podman・カーネル・Codex・bwrap の版、プロセス権限、`/proc` の mountinfo、生の bwrap（新規 procfs 有無）、Codex 自身の read-only / workspace-write 実行と各終了コード。診断スクリプトの終了コード 0 は採取完了を表し、各プローブ成功や修正完了を意味しない。ENTRYPOINT を置き換えるため、製品のファイアウォール・capability 剥奪経路・MCP 審査の受入検証を代替しない。

修正後は通常の c3c 起動でコンテナを再作成し、Codex の `pwd` / `git status`、読み取り専用保護、非特権の iptables 操作拒否、許可／禁止通信を確認する。本件の findsummits では上記の受入報告によりクローズ済みである。

## 初期調査を行った開発環境での検証

- `./lint.sh`: シェル検査は成功。Podman 不在による Compose 検証スキップの警告あり。
- `./c3c --check /workspace`: FAIL。この環境に設定先の `SECRETS_DIR` と `CODEX_DIR` が存在しないため。イメージ診断は Podman 不在でスキップ。#140 の再現結果ではない。
- 初版の実 Podman 診断: ユーザーのホスト実行結果を上記へ記録済み。
- 第2回の実 Podman 比較: ユーザー実行済み。ただし診断コマンドの誤りにより、意図したコマンド・ポリシーの検証は未成立。
- 訂正後の `codex sandbox -c 'sandbox_mode="read-only"' -- /bin/pwd`: 開発環境で rc 0。
- 訂正後の実 Podman 比較: ユーザー実行済み。システム版では2コマンドとも失敗、同梱版では2コマンドとも成功。
- HOME 警告修正後の診断再実行、通常 c3c 起動、findsummits での解消確認: この初期調査環境では **not run**（Podman と対象ホストへの接続がない）。後続の利用側受入は前節の報告を参照。


## 公開前のホスト再検証（2026-09-22）

HOME / XDG_CONFIG_HOME 修正を含む公開版スクリプトを、前述のイメージ ID `5705bfe0…06c5` に対して実行した。Podman 5.8.6、カーネル 7.2.6-local、Codex 0.155.1、システム版 bubblewrap 0.12.0。スクリプト全体は rc 0（採取完了）だった。

- システム版: 新規 `/proc` の生 bwrap は rc 1、既存 `/proc` 継承は rc 0。Codex の read-only `pwd` と workspace-write `git status` は両方 rc 1 で、同じ `/proc` マウント失敗を再現した。
- 同梱版: 両 Codex コマンドは rc 0。`/root/.config/git/ignore` の警告は出なかった。
- 両ケースとも CapInh/CapPrm/CapEff/CapAmb=0、Seccomp=2、`/proc` のマスク・読み取り専用マウントを確認した。CapBnd は非ゼロ、NoNewPrivs=0 の診断初期化経路であり、製品 ENTRYPOINT の受入と混同しない。
- `./lint.sh`: rc 0、Compose 検証込みで成功。`git diff --check`: rc 0。
- この公開作業での全体ビルド・通常起動の受入再実行: **not run**。製品コードの変更はなく、利用側の通常起動と境界の結果は上記の完了報告を参照する。
