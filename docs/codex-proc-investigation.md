# Codex の /proc マウント失敗（#140）

2026-09-22 の調査記録。対象は [#140](https://github.com/jj1xgo/c3c/issues/140)。#140 の時点では製品の起動設定を変更していない（#145 の変更は後述「#145: 同梱版の優先」）。システム版 bubblewrap の追加を戻して再ビルドした利用側から、通常起動と境界の受入完了が報告され、issue はクローズ済み（後述「利用側の受入結果」）。

## 確認できたこと

報告されたホスト比較では、bubblewrap 0.12.0 に `--proc /proc` を渡すと `Can't mount proc on /proc: Operation not permitted` で失敗し、Podman の `unmask=/proc/*` を追加すると成功する。ただし ENTRYPOINT を置き換えた比較であり、この比較単独では通常の c3c 起動経路の成功を確認していない。

別の原因候補として、Codex の失敗検出と bubblewrap のエラー表記の不一致を確認した。

- [Codex 0.155.1 の `run_bwrap_with_proc_fallback()` と `preflight_proc_mount_support()`](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/linux-sandbox/src/linux_run_main.rs) は、本コマンドの前に `/proc` の新規マウントを試す。認識できたマウント失敗なら `mount_proc=false` に切り替える。
- 同ファイルの `is_proc_mount_failure()` は、エラーに `Can't mount proc` と `/newroot/proc` の両方に加えて、`Invalid argument`・`Operation not permitted`・`Permission denied` のいずれかを含むことを要求する。報告の `/proc` はこの条件に一致しない。
- [bubblewrap 0.12.0 の `SETUP_MOUNT_PROC` 処理](https://github.com/containers/bubblewrap/blob/v0.12.0/bubblewrap.c) は、エラー表示に `op->dest` を使う。`--proc /proc` なら報告と同じ `/proc` になる。
- [Codex 0.155.1 の launcher](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/linux-sandbox/src/launcher.rs) は、必要な機能を持つシステム版 bwrap を同梱版より先に選ぶ。

報告者がホストで初版の診断スクリプトを実行した結果、実 Codex 0.155.1、システム bubblewrap 0.12.0 を確認した。Podman 5.8.6、カーネル 7.2.6-local。結果は次のとおり。

| 検査 | 終了コード・結果 |
| --- | --- |
| bwrap、新規 `/proc` あり | 1、`Can't mount proc on /proc: Operation not permitted` |
| bwrap、既存 `/proc` 継承 | 0、`OK` |
| Codex 診断呼出し（引数に誤り、下記参照） | 両方とも 1、同じマウントエラー |

CapInh/CapPrm/CapEff/CapAmb はゼロ、Seccomp=2。`/proc` 配下のマスクと読み取り専用マウントも採取できた。自動切替の失敗という仮説と整合するが、Codex が選択した実バイナリのトレースは未実施。

初版は `CODEX_HOME` を `/tmp` に置いたため helper alias 作成拒否の警告も出た。これは診断側の不備なので `/home/node` 配下へ修正した。マウントエラーとの因果を混同せず、修正版で再比較した（以下）。

### 第2回の比較と診断コマンドの訂正

同じイメージで system / bundled の比較を報告者が実行した。helper alias の警告は解消。system は引き続き `/proc` マウントエラー（rc 1）、bundled は `Failed to execvp linux: No such file or directory`（rc 101）となった。

診断スクリプトの `codex sandbox linux -c ... -- ...` が誤りだった。0.155.1 の実機 `codex sandbox --help` と [CLI の `HostSandboxArgs` および `Subcommand::Sandbox` の実装](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/cli/src/main.rs) を確認したところ、OS 名のサブコマンドはなく、正しくは `codex sandbox -c ... -- ...`。`linux` は実行するコマンドとして扱われていた。このため、これまでの2回を read-only の `pwd` / workspace-write の `git status` の実行検証とは扱わず、指定したポリシーの適用確認も取り消す。

bundled の結果は exec 段階まで進んだことを示すが、目的のコマンドの成功ではない。スクリプトから `linux` を除き、実 argv をログに表示するようにした。修正した read-only の `pwd` は開発環境の Codex 0.155.1 で rc 0、`/workspace` の出力を確認した（二重サンドボックス内では内部ロックの書込みが失敗したため、承認済みの外側実行で確認）。この時点では対象ホストの同じイメージでの正しい呼出しの比較が残っていた。

### 第3回の比較（正しい CLI 呼出し）

報告者が同じイメージ（ID `5705bfe02f86ce01d31b5455d894f85b1e3f089286a6bcd248a704e039db06c5`）で訂正後のスクリプトを実行した。

| 実行 | システム版 0.12.0 | Codex 同梱版 |
| --- | --- | --- |
| `codex sandbox -c 'sandbox_mode="read-only"' -- /bin/pwd` | rc 1、`/proc` マウント失敗 | rc 0、診断リポジトリのパス |
| `codex sandbox -c 'sandbox_mode="workspace-write"' -- git status --short --branch` | rc 1、`/proc` マウント失敗 | rc 0、空の Git リポジトリの状態 |

両ケースの `/proc` マスク・読み取り専用マウント、Seccomp=2、CapInh/CapPrm/CapEff/CapAmb=0 は同じ。少なくともこの環境では、Podman の保護設定を緩めず同梱版で実行できることが確認できた。失敗判定の不一致というソース上の説明とも整合する。同梱版が新規 procfs をマウントしたのか、自動切替で既存 `/proc` を継承したのかは未計測である。読み取り専用保護に対する書込み拒否や、製品の起動経路全体の受入はこの比較では検証していない。後述の利用側受入は Podman 層の保護も別途確認している。

同梱版の Git で `/root/.config/git/ignore` の Permission denied 警告が出た。診断用 root 初期化から uid 1000 へ移る際に HOME が残ったため、スクリプトに `HOME=/home/node` と `XDG_CONFIG_HOME=/home/node/.config` を明示した。この時点では警告修正後の実 Podman 再実行は未実施で、上表は修正前の報告者の実行結果である。公開前の再実行結果は末尾に記す。

## 利用側の受入結果

2026-09-22 の [findsummits 側の完了報告](https://github.com/jj1xgo/c3c/issues/140#issuecomment-5769730943)では、bubblewrap 追加を戻したコミット `9c1f89e` を再ビルドし、通常起動した別コンテナで次を確認した。これは上記の ENTRYPOINT を置き換えた比較とは別の、利用側セッションによる受入結果である。

- システム版 bwrap は未導入。同梱版は実行可能。
- 通常の Codex サンドボックス内で `pwd` と `git status` が rc 0。サンドボックス外への切替なし。
- `.gitconfig` と Codex MCP 承認ファイルの書込み用 open は EROFS、`/proc/sys/kernel/hostname` と `/proc/sysrq-trigger` は EACCES。書込み・truncate は実施していない。
- `/proc` のマスク・読み取り専用マウントを維持。非特権ユーザーの `iptables -S` / `ip6tables -S` は拒否。
- コンテナ側で確認した IPv4 HTTPS は、許可先2件に接続成功、禁止先2件に接続失敗。Codex 自身のネットワーク禁止をコンテナの拒否として数えていない。
- コンテナ側は CapInh/CapPrm/CapEff/CapAmb=0・Seccomp=2、Codex サンドボックス内は CapBnd を含め capability=0・Seccomp=2・NoNewPrivs=1。

再ビルドと通常起動は報告者による確認済み。この範囲で issue の受入条件を満たしてクローズした。IPv6 実通信と c3c 全体の回帰テストは、この利用側受入では **not run**。上記の結果をすべてのホスト・版に一般化しない。

## 対応方針

今回の利用側では、Codex のために追加したシステム版 bubblewrap を外し、同梱版を使う方針とし、上記の通常起動で受入を完了した。他のツールがシステム版へ依存していないかを確認したうえで、利用側の `.c3c/packages.txt` の追加行を戻し、`c3c codex -b <project>` で再ビルド・起動する。c3c 同梱の `packages.txt` と `Dockerfile.claude` は bubblewrap を明示追加していないため、本体でパッケージを一律削除する変更は不要。間接依存等でシステム版が残る場合は、依存関係を確認し、強制削除しない。

起動後は `command -v bwrap` でシステム版が残っていないこと、Codex の通常のサンドボックス付きコマンド実行で `pwd` / `git status` が成功することを確認する。今回の2ケース比較は成立したので、HOME 警告だけのために同じ診断を繰り返す必要はない。同様の環境へ適用する場合の受入は、製品の通常起動で行う。

以上は #140 当時の回避策で、記録として残す。[#145](https://github.com/jj1xgo/c3c/issues/145) 以降は、システム版が間接依存で残るイメージでも Codex 経路で同梱版を選ぶ（次節）。

上流の失敗検出修正も候補として残す。独自の stderr 書き換えラッパーや sandbox 無効化は導入しない。

`unmask=/proc/*` は解消条件として報告されているが、本件では既定へ追加しない。[Podman の仕様](https://docs.podman.io/en/v4.4/markdown/options/security-opt.html)では unmask は既定のマスクと読み取り専用保護に関わる設定であり、`/proc/sys` 等への影響も評価が必要。個別パスの最小化も未検証。既存 `/proc` を継承する方式も新規 PID namespace に対応する procfs とは異なるため、保護範囲が同じとは扱わない。

## #145: 同梱版の優先

画像ライブラリ等の間接依存でシステム版 bubblewrap が入るプロジェクトでは、依存パッケージを外すと別の機能が壊れる。そこで c3c は依存パッケージを削除せず、Codex の選択だけを同梱版へ向ける。ビルド時に同梱実体への固定 symlink `/usr/local/libexec/c3c/codex-bwrap/bwrap` を作り、`entrypoint.sh` の Codex 経路でこのディレクトリを PATH の先頭へ加える。設計の詳細と対象外の条件は README「Codex CLI を対話で使う」節を参照する。

この修正で使われるのは、Codex 自身の proc fallback である。同梱版は新しい procfs のマウントに失敗し、Codex が失敗を認識して `mount_proc=false` で再実行する。sandbox は外側コンテナの procfs を引き継ぐ。システム版 0.12.0 は失敗の表記が一致しないので fallback が働かない（上記「確認できたこと」）。新しい procfs とは保護範囲が異なるので、外側プロセスの見え方を受入で確かめる（次節）。

### #145 の受入

2026-09-23、ホスト（x86_64、Podman）で確認した。修正版の c3c はブランチ `fix/issue145-codex-bundled-bwrap` の `be92aa6`、Codex は 0.156.0。対象は隔離した fixture プロジェクトで、`.c3c/packages.txt` に `glycin-loaders` と `libgdk-pixbuf2.0-bin` を入れた。利用側 repo の設定と持ち主の認証ディレクトリは使っていない。

**修正前**: SOTLAS の既存イメージ（image `e49bc3f57f82`、Codex 0.155.1、`/usr/bin/bwrap` 0.12.0）に `tests/diagnose-codex-proc.sh` を実行した。システム版のままでは read-only の `pwd` と workspace-write の `git status` がともに rc 1、`Can't mount proc on /proc` で失敗した。システム版を外した比較では、両方とも rc 0 だった。修正版の `c3c --check --agent codex` は、このイメージの境界アセットのドリフトを WARNING で報告した。

**修正後の通常起動**: `c3c codex -b <fixture>` で再ビルドした（image `86609e5ec220`）。イメージには glycin-loaders の依存として `/usr/bin/bwrap` 0.12.0 が残っている。TTY 無しで起動すると、製品 ENTRYPOINT が firewall の自己検証、MCP 審査の snapshot、承認（対象 0 件）、verify、Codex の exec まで進んだ。稼働中のコンテナでは、Codex の node ラッパーとネイティブ本体の PATH の先頭が `/usr/local/libexec/c3c/codex-bwrap` だった。`podman exec` のシェルとイメージ既定の PATH は従来のままで、Claude 経路で名前解決される bwrap は `/usr/bin/bwrap` だった。未承認・変更された stdio MCP（`command = "bwrap"`）を足すと、TTY 無しでは Codex を起動せずに拒否した。

**sandbox の診断**: ChatGPT 認証なしでは agent に通常ツールを実行させられない。そこで同じ稼働コンテナで、Codex と同じ PATH と ENTRYPOINT と同じ `setpriv` の剥奪を与え、`codex sandbox` を実行した。これは診断で、通常ツールの受入の代わりにはならない。

| 確認 | 結果 |
| --- | --- |
| read-only / workspace-write の `pwd` | 両方 rc 0、`/workspace` |
| sandbox 実行中の bwrap の実体（sandbox 外の同 uid から `/proc/<pid>/exe`） | npm の `codex-resources/bwrap`（同梱版） |
| `git status --short --branch` | rc 128。fixture は `GITCONFIG_FILE` 未設定で `~/.gitconfig` が `/dev/null` の bind（デバイス）になり、sandbox 内で読めない。`GIT_CONFIG_GLOBAL=/dev/null`（sandbox 内の `/dev`）では両モード rc 0。#145 とは別の要因 |
| PID namespace と `/proc` | sandbox の PID namespace は外側と別だが、`/proc` には外側の PID（tini・Codex の node ラッパー・ネイティブ本体・firewall-refresh 等）が見える。fallback で外側の procfs を引き継いでいる |
| 外側プロセスの `environ` / `cmdline`（O_RDONLY の open だけ） | node ラッパーと Codex 本体の `environ` は両方拒否、`cmdline` は open できる |
| 書込の open（write・truncate なし） | read-only で `/workspace/README.md` は EROFS。両モードで `/proc/sys/kernel/hostname`・`/proc/sysrq-trigger` は EACCES。workspace-write で `~/.codex/config.toml` は EROFS、固定リンクは EACCES |
| プロセス制限 | CapInh/Prm/Eff/Bnd/Amb=0、NoNewPrivs=1、Seccomp=2 |
| `shell_environment_policy.set.PATH="/usr/bin:/bin"` を指定 | 元の `Can't mount proc on /proc` で rc 1（文書化した対象外条件が実在する） |

コンテナ側では、非特権の `iptables -S` が拒否され、Codex プロセスの capability は 0 だった。HTTPS は `api.github.com` が 200、`example.com` と `http://api.github.com` は接続できなかった。node は固定リンク・その親・同梱実体とその親のいずれにも書き込めない（root:root、755）。

**not run と限界**:

- ChatGPT 認証済みの対話セッションで、agent の通常ツールとして `pwd` / `git status` を実行する受入は未実施。持ち主のセッションで行う。
- glycin の画像処理は、この image の gdk-pixbuf が libglycin にリンクしておらず、glycin を通る入口を用意できなかった。PNG のサムネイル生成は、既定 PATH と Codex の PATH の両方で成功した（gdk-pixbuf 内蔵のローダー）。Codex の子プロセスからの glycin の互換は主張しない。
- arm64 は fixture の単体試験だけで、実機は未確認。IPv6 の実通信も未確認。
- 外側プロセスの `environ` が読めないという結果は、上記 2 プロセスとこの版に限る。全プロセスが不可視とは主張しない。

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
- 第2回の実 Podman 比較: 報告者の実行済み。ただし診断コマンドの誤りにより、意図したコマンド・ポリシーの検証は未成立。
- 訂正後の `codex sandbox -c 'sandbox_mode="read-only"' -- /bin/pwd`: 開発環境で rc 0。
- 訂正後の実 Podman 比較: 報告者の実行済み。システム版では2コマンドとも失敗、同梱版では2コマンドとも成功。
- HOME 警告修正後の診断再実行、通常 c3c 起動、findsummits での解消確認: この初期調査環境では **not run**（Podman と対象ホストへの接続がない）。後続の利用側受入は「利用側の受入結果」節、診断再実行は次の「公開前のホスト再検証」節を参照。

## 公開前のホスト再検証（2026-09-22）

HOME / XDG_CONFIG_HOME 修正を含む公開版スクリプトを、前述のイメージ ID `5705bfe0…06c5` に対して実行した。Podman 5.8.6、カーネル 7.2.6-local、Codex 0.155.1、システム版 bubblewrap 0.12.0。スクリプト全体は rc 0（採取完了）だった。

- システム版: 新規 `/proc` の生 bwrap は rc 1、既存 `/proc` 継承は rc 0。Codex の read-only `pwd` と workspace-write `git status` は両方 rc 1 で、同じ `/proc` マウント失敗を再現した。
- 同梱版: 両 Codex コマンドは rc 0。`/root/.config/git/ignore` の警告は出なかった。
- 両ケースとも CapInh/CapPrm/CapEff/CapAmb=0、Seccomp=2、`/proc` のマスク・読み取り専用マウントを確認した。この診断では CapBnd は非ゼロ、NoNewPrivs=0 だった。製品も bounding set は保持するが、この診断は Compose の `cap_add` を使わず、製品 ENTRYPOINT も通らないため、権限設定全体の同一性は主張しない。
- `./lint.sh`: rc 0、Compose 検証込みで成功。`git diff --check`: rc 0。
- この公開作業での全体ビルド・通常起動の受入再実行: **not run**。製品コードの変更はなく、利用側の通常起動と境界の結果は上記の完了報告を参照する。
