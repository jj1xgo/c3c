# claude-container

[sethjensen1/claude-container](https://github.com/sethjensen1/claude-container) をフォークした Podman 上の Claude Code コンテナ実行環境。

Podman + Compose を使い、ホストの Claude 認証情報を共有しながら任意のディレクトリを `/workspace` にマウントして Claude Code を起動する。

apt/pip パッケージは `.claude-container.d/`（後述）でプロジェクトごとに指定でき、claude-container リポジトリ自体にはプロジェクト固有のパッケージを持たせない。

- [前提](#前提)
- [使い方](#使い方)
- [起動前チェック（--check）](#起動前チェックcheck)
- [環境変数](#環境変数)
- [IPv6 を任意で有効にする](#ipv6-を任意で有効にする)
- [ホストの指示ファイルとスキルをコンテナ内で解決する](#ホストの指示ファイルとスキルをコンテナ内で解決する)
- [利用側プロジェクトの設定](#利用側プロジェクトの設定)
- [GitHub トークンの配線](#github-トークンの配線)
- [MCP サーバーの追加](#mcp-サーバーの追加)
- [Codex CLI をセカンドオピニオンとして使う](#codex-cli-をセカンドオピニオンとして使う)
- [アーキテクチャ](#アーキテクチャ)
- [イメージの変更](#イメージの変更)
- [コンテナ間の永続化](#コンテナ間の永続化)
- [何ができて何ができないか（git / gh / PAT / hook 早見表）](#何ができて何ができないかgit--gh--pat--hook-早見表)
- [セキュリティモデル](#セキュリティモデル)
- [Podman 固有の注意](#podman-固有の注意)
- [変更後の確認](#変更後の確認)
- [表記](#表記)
- [バージョニング](#バージョニング)
- [参考](#参考)
- [ライセンス](#ライセンス)

## 前提

- [Podman](https://podman.io/) および `podman-compose`
- ホストの取得処理に `curl`、`jq`、GNU coreutils の `timeout`
- ホストに `~/.claude.json`（Claude 認証情報）が存在すること

## 使い方

```bash
# 任意のディレクトリで Claude Code を起動
./claude-container /path/to/project

# イメージを強制リビルドして起動
./claude-container -b /path/to/project

# そのプロジェクトのイメージ・ネットワーク・ビルドコンテキストを削除して終了
./claude-container --clean /path/to/project

# 全プロジェクト分のイメージ・ネットワーク・ビルドコンテキストを削除して終了
./claude-container --clean

# 起動せず設定を診断（引数なしなら起動台帳の全プロジェクトを一括診断）
./claude-container --check
./claude-container --check /path/to/project
```

スクリプトはシンボリックリンク経由でも動作する（`readlink` で自身のパスを解決する）。異なるターゲットプロジェクトを交互に起動・リビルドしても互いのイメージ・ビルドコンテキストを上書きしない（後述「アーキテクチャ」参照）。同時に別々のプロジェクトを起動することもできる。

通常起動には実在してアクセスできるディレクトリが必要で、不正なパスは `ERROR:` で案内する。`--clean <ディレクトリ>` は、削除済みでも起動台帳（`~/.local/state/claude-container/projects`）に同じ絶対パスが残っていれば実行できる。相対パス・`.`・`..`・末尾の `/` は正規化し、シンボリックリンクの綴りは起動時と同じものを使う（リンク先の実体パスとは別プロジェクト扱い）。先頭が `//` の綴りで起動したプロジェクトは対象外（bash は先頭の `//` を保持し `realpath` は `/` に畳むため、削除後の照合が一致せずエラーで停止する）。台帳にない削除済みパスや、改行を含む削除済みパスからは清掃対象を推測せず、エラーで停止する。対象のイメージ・ネットワーク・ビルドコンテキスト・MCP 承認記録・台帳エントリを清掃するほか、従来どおり最後に dangling イメージ全体を整理する。

`CDPATH` を使って相対パスから起動したプロジェクトを削除した場合は、起動台帳に記録された絶対パスを `--clean` に指定する。削除済みパスの復元では `CDPATH` を探索しない。

## 起動前チェック（`--check`）

複数のファミリープロジェクトが本リポジトリを直接参照して稼働している運用（内部運用issue参照）では、破壊的変更（v3.0.0 の旧設定形式削除、v4.0.0 のトークン配線変更等）の後、各プロジェクトの設定を更新しないと起動が fail-closed ガードで停止する。`--check` は起動せずにこれを事前診断し、リビルド・起動前に必要な移行作業を一括提示する。

```bash
# 起動台帳（後述）の全プロジェクトを一括診断
./claude-container --check

# 個別のディレクトリを診断（複数指定可）
./claude-container --check /path/to/project-a /path/to/project-b
```

- **起動台帳**: 通常起動（`--clean`/`--check` を除く）のたびに、対象ディレクトリのホスト絶対パスが `~/.local/state/claude-container/projects` へ自動記録される（手動メンテ不要）。`--check` を引数なしで実行すると、この台帳に記録された全プロジェクトを一括診断する。`--clean <directory>` はそのプロジェクトを台帳からも削除し、`--clean`（引数なし）は台帳自体を削除する。シンボリックリンク経由と実体パスで起動すると別エントリとして記録される点に注意（`compute_project_name()` のプロジェクト識別基準と同じ）。
- **検査項目**: legacy トークン変数（`GH_TOKEN_FILE` 等）・`SHARED_MOUNT`/`SHARED_MOUNT_HOME_ALIAS`/`AGENTS_DIR`/`GITCONFIG_FILE`/`SECRETS_DIR`/`CODEX_DIR` の存在とレイアウト（`noexport/` 残存等）・パーミッション・`packages.txt`/`requirements.txt`/`allowed-domains.txt` の有無・イメージの既ビルド有無（`podman` 利用可能な場合のみ）・MCP 監査ゲートの承認状態・`packages.txt`/`requirements.txt` の内容診断。**起動時ガードと内容診断は別モードで動く**: 上記の有無チェック等は通常起動時の fail-closed ガードと同一の関数を共有し診断結果と実際の起動挙動が乖離しないが、内容診断（`packages.txt`/`requirements.txt` の allowlist 検証）は `--check` 専用の助言診断で、通常起動時の強制点（`Dockerfile.claude` の `RUN`）とは別に呼ばれる。ただし両者は同じ `validate-build-input.sh` を呼ぶため、判定ロジック自体が乖離することはない。
- **非対話・対象リポジトリは不変**: `--check` は TTY 確認を一切行わない（MCP stdio 型サーバーが未承認の場合は「初回起動時に確認プロンプトが出ます」と報告するのみ）。台帳に記録があるが実体が見つからないプロジェクトも FAIL として報告するだけで、台帳を黙って書き換えない。**保証の範囲は「対象リポジトリと `.build-context/` を変更しない」こと**（内容診断は `mktemp` 経由で `/tmp` 配下に作業ファイルを必ず作るため、無限定の「書き込みゼロ」ではない）。
- **終了コード**: 診断対象のいずれかが FAIL の場合は非0、それ以外は0で終了する。`-b` は `--check` と併用しても無視される。

## 環境変数

**利用側プロジェクト**のルートに `.claude-container.d/env` を置くと起動前に自動で読み込まれる。読み込まれるのは `KEY=VALUE` 形式の行のうち **下表のキーだけ**で、クォートやシェル展開は解釈されない（ホスト上でのシェル構文の即時解釈を避けるため、意図的に `source` していない）。下表にないキーは export されず `WARNING` を出して無視する（[`#44`](https://github.com/jj1xgo/claude-container/issues/44)。`PATH`・`HOME`・`LD_PRELOAD` 等、ホスト側で動くランチャーや podman・git・gh の挙動を変えうるキーをリポジトリ側から書けないようにするため）。また、対象プロジェクト直下の `.env` は compose の変数補間に使わない（`podman compose` を `--env-file /dev/null` で呼ぶ。[`#60`](https://github.com/jj1xgo/claude-container/issues/60)）。リポジトリ同梱のファイルから設定できる入口は `.claude-container.d/env` の 1 つだけである（シェル環境から渡した変数は従来どおり有効なので、以前 `env` に書いて効いていた `PATH`・`PODMAN_COMPOSE_PROVIDER`・`CLAUDE_CODE_VERSION` 等はシェル環境へ移すこと。例: `CLAUDE_CODE_VERSION=1.2.3 ./claude-container <dir>`）。これはビルド時に焼き込まれる設定ではなく起動のたび毎回読み込まれるランタイム設定なので、変更してもリビルド（`-b`）は不要。

| 変数 | デフォルト | 説明 |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | `~` | `.claude.json` と `.claude/` が置かれているディレクトリ。後述「ホストの Claude Code 設定の読み取り専用保護」の基点でもある。絶対パスか `~/` 始まりで指定する（相対パスは起動を中止する） |
| `EXTRA_MOUNT` | `/dev/null` | コンテナ内 `/data` に追加でマウントするホスト側パス |
| `SHARED_MOUNT` | `/dev/null` | コンテナ内 `/shared` に追加でマウントするホスト側パス。複数プロジェクトからの共有ディレクトリ参照向け（`EXTRA_MOUNT` と併用可）。設定済みでパスが無い場合は起動を中止 |
| `SHARED_MOUNT_HOME_ALIAS` | `0` | `1` で `SHARED_MOUNT` のディレクトリを、`/shared`（rw）に加えてコンテナ内の `~`（`/home/node`）配下の同じ相対位置と、ホストと同じ絶対パスにも `:ro` で重ねる（後述「ホストの指示ファイルとスキルをコンテナ内で解決する」節）。`SHARED_MOUNT` がホストの `$HOME` 配下で、`$HOME` 直下の項目名が `.` で始まらないことが条件。ホスト絶対パス別名がコンテナの予約領域（下記参照）と重なる場合も拒否する。条件を満たさない値と `0`/`1` 以外の値は起動と `--check` で拒否 |
| `AGENTS_DIR` | (unset) | Codex 等のエージェント共通のスキル置き場（通常 `~/.agents`）をコンテナ内 `~/.agents` として `:ro` マウントするホスト側パス。絶対パスか `~/` 始まりで指定する。`~/.claude/agents/`（Claude Code の subagent 定義、後述の `:ro` 保護 11 項目の一つ）とは別物 |
| `TZ` | ホストから自動検出 | コンテナ内のタイムゾーン |
| `CLAUDE_CONTAINER_IPV6` | `0` | `1` で IPv4/IPv6 を併用し両方に許可リストを適用する。未指定・空・0は既存IPv4モード、その他は起動と `--check` で拒否。初回は対応イメージの `-b` が必要（後述） |
| `CLAUDE_CONTAINER_NO_FIREWALL` | (unset) | `1` でエグレス制限（後述）を無効化 |
| `GITCONFIG_FILE` | (unset) | コンテナ内 `~/.gitconfig` として read-only マウントするホスト側 git 設定ファイルのパス（後述） |
| `SECRETS_DIR` | (unset) | GitHub トークン等のシークレットをコンテナへ持ち込む唯一の機構のホスト側パス（後述「GitHub トークンの配線」節） |
| `CODEX_DIR` | (unset) | Codex CLI の認証情報ディレクトリ（`auth.json` 等）をコンテナへ rw マウントするホスト側パス。専用ディレクトリを推奨（後述「Codex CLI をセカンドオピニオンとして使う」節）。絶対パスか `~/` 始まりで指定する（相対パスは起動を中止する）。実ホストの `~/.codex` と同じ実体を指す指定（表記ゆれ・シンボリックリンクを含む）は起動を中止する |

`TZ` は起動スクリプトがホストの `/etc/timezone`（なければ `/etc/localtime` シンボリックリンク）から自動検出する。`.claude-container.d/env` またはシェル環境で明示した場合はそちらが優先される。

claude-container 自身を対象プロジェクトとして自己ホスト起動する場合（このリポジトリを直接 `./claude-container` の引数に渡す場合）は、`.claude-container.d/env.example` をコピーして `.claude-container.d/env` を作成する。`SECRETS_DIR` 等ホスト固有のパスを含みうるため `.claude-container.d/env` は gitignore 対象で、リポジトリには example のみをコミットする。同様に、GitHub 公式 MCP サーバー（後述「GitHub トークンの配線」節のレシピ参照）を自己ホスト環境でも使いたい場合は、`.mcp.json.example` をコピーして `.mcp.json` を作成する（`.mcp.json` はメンテナ自身のセッション用実設定のため gitignore 対象）。

## IPv6 を任意で有効にする

既定は IPv4 のみ。IPv6 も使うプロジェクトは `.claude-container.d/env` に次を追加する:

```text
CLAUDE_CONTAINER_IPV6=1
```

初回は `./claude-container -b /path/to/project` で新しい境界アセットを含むイメージを作る。対応ラベルのない旧イメージでの有効化は、起動と `--check` で再ビルドを案内して停止する。その後の0/1の切り替えはランタイム設定なので、コンテナを終了して起動し直せば反映される。IPv4/IPv6 で `allowed-domains.txt` と `allowed-ports.txt` を共用し、IPv6 でも未許可の宛先・ポートを遮断する。IPv6-only ホストは初期対応の対象外で、IPv4 も使用できることが前提。

有効時は launcher が固定の `compose.ipv6.yml` を追加し、単独 pasta と仮想 IPv6 ゲートウェイ `fe80::1` を使う。Podman/pasta、ホストの IPv6 外向き通信と、ip6tables の hop-limit / REJECT 機能を使えるカーネルが必要。これらが使えない場合は初期化を失敗として停止する。今回確認した環境は rootless Podman 5.8.6 / podman-compose 1.6.0。ホストに IPv6 があっても rootless bridge の外側へ経路が渡らない場合があるため、コンテナ単位に閉じた pasta を使う。ホスト・ルーター・WARP の設定は自動変更しない。起動時には経路、IPv6 有効状態、ip6tables、`api.anthropic.com` の IPv6 HTTPS 接続と禁止先の遮断を検査し、失敗したら起動を止める。`--check` は設定値だけを検査し、ネットワーク作成や実疎通は行わない。

既定の IPv4 モードは既存 bridge のまま。有効時は共有 bridge を再利用せず、pasta はコンテナ終了時に片付く。過去の bridge は必要なら既存の `--clean <project>` で整理する。pasta で検出する IPv4 ゲートウェイは物理側ルーターの場合があり、bridge のゲートウェイと同じホストサービスの別名ではない。Podman は既定で `--no-map-gw` を指定し、ゲートウェイからホスト loopback への写像を無効にする（[Podman のネットワーク仕様](https://docs.podman.io/en/v5.8.0/markdown/podman-run.1.html#network-mode-net)）。IPv6 ゲートウェイへの TCP/UDP 全許可は追加しない。ホスト側サービスへの接続があるプロジェクトは切り替え時に確認する。

IPv6 の許可対象は `2000::/3` の global unicast と `fc00::/7` の ULA。未指定・loopback・IPv4-mapped・multicast・link-local などの AAAA 応答は警告して除外する。link-local 宛てサービスや変換用プレフィックスの明示許可は初期対応外。DNS リゾルバへの53番と、近隣探索・Path MTU Discovery 等に必要な ICMPv6 は別ルールで許可する。AAAA がない正常応答と NXDOMAIN はスキップし、一時的な解決失敗は起動時にエラー、定期更新時に警告とする。IPv6 のルールも約15秒ごとに更新し、約3分観測されないものを削除する。

アドレス表記の正規化と IPv6 ルール管理には、イメージに固定導入する `python3` と root 所有の `ipv6-firewall.py` を使う。追加の Python パッケージは不要。`CLAUDE_CONTAINER_NO_FIREWALL=1` を明示した場合は、既存の無効化設定として IPv4/IPv6 両方のファイアウォール初期化を省略する。

## ホストの指示ファイルとスキルをコンテナ内で解決する

ホストの `~/.claude/CLAUDE.md` はコンテナへ `:ro` で共有される（後述「ホストの Claude Code 設定の読み取り専用保護」）。その中で `@~/obsidian-vault/knowledge/索引.md` のように `~` 起点で別のディレクトリを参照していると、コンテナ内の `~` は `/home/node` なので参照先が無く、指示が展開されない。同様に Codex 等が共通で読む `~/.agents/skills/` もコンテナ内には無い。グローバル指示をホストとコンテナで二重管理せず、参照先をコンテナ側で解決するための opt-in が 2 つある（[`#99`](https://github.com/jj1xgo/claude-container/issues/99)）。

```bash
# .claude-container.d/env
SHARED_MOUNT=~/obsidian-vault
SHARED_MOUNT_HOME_ALIAS=1
AGENTS_DIR=~/.agents
```

- `SHARED_MOUNT_HOME_ALIAS=1`: `SHARED_MOUNT` の実体が、従来の `/shared`（rw）に加えて、コンテナ内の `~` 配下の同じ相対位置（例 `/home/node/obsidian-vault`）と、ホストと同じ絶対パス（例 `/home/<host user>/obsidian-vault`）にも `:ro` で見える。`@~/...` の参照は前者で、ホストの絶対パスを書いた参照は後者で解決する。ホストの `$HOME` が `/home/node` なら両者は同じなので別名は 1 本になる。条件は `SHARED_MOUNT` がホストの `$HOME` 配下（`$HOME` 自身は不可）で、`$HOME` 直下の項目名が `.` で始まらないこと（`~/.claude`・`~/.codex` 等の設定・認証領域は別名にしない）。`..`・コロン・制御文字を含む値、`0`/`1` 以外の値は起動と `--check` で拒否する。ホスト絶対パス別名が `/workspace`・`/data`・`/shared`・`/home/node`・`/bin`・`/sbin`・`/lib`・`/lib64`・`/usr`・`/etc`・`/proc`・`/sys`・`/dev`・`/run`・`/var`・`/opt`・`/root` と一致するか、どちらかが他方を含む場合も、予約領域の内容を隠さないため起動と `--check` で拒否する（2 つの別名が一致する場合を除く）。HOME が `/var/home/<user>` や `/root` の構成もこの制約に該当し、共有別名の opt-in は利用できない。ホスト絶対パス別名とコンテナ HOME 側の別名が互いを含む場合も拒否する。`SHARED_MOUNT` にシンボリックリンクを指定した場合、別名の綴りはリンクのままで、`/shared` を含む 3 箇所の source はリンク先の実体になる。
- `AGENTS_DIR`: 指定したディレクトリをコンテナ内 `/home/node/.agents` に `:ro` で付ける。`~/.claude/agents/` とは別物。指定先が `EXTRA_MOUNT`・`SHARED_MOUNT`・`CODEX_DIR`・対象プロジェクト・`~/.claude` の範囲と重なると、別経路からの書き込みの可能性を示す WARNING を出す（起動は止めない）。検出はパスの包含関係のみで、たとえば `~/.claude/agents` のように既存の `:ro` 保護対象そのものを指定した場合も警告されるが、その保護されたマウント経由では書けない。

どちらもランタイムの bind mount なので `-b` なしで効くが、override ファイルが境界アセットのハッシュ対象に入るため、既存イメージでは `-b` するまで起動時にドリフトの WARNING が出る。**別名の `:ro` は境界ではない**: 同じ実体が `/shared` に rw であるため、コンテナ内のコードは `/shared` 経由で書ける。`:ro` は「書き込みは `/shared` 経由で行う」運用の目印で、別名経由の書き込みが Read-only file system で失敗するだけに留まる。`AGENTS_DIR` の override 自体は rw の経路を追加しない（`/shared` のような対になる rw マウントが無い）。ただし上記 WARNING が検出するのは source ディレクトリ同士のパスの包含だけで、ディレクトリ内部の symlink や hard link で別の rw マウントと実体を共有している場合は検出しない。`--check` は有効時に `[OK]   共有別名 (ro): ...` と `[OK]   AGENTS_DIR: ...` を表示する。

## 利用側プロジェクトの設定

bash history はターゲットプロジェクトの `.claude/bash_history` に保存される。誤ってコミットしないよう、ターゲットプロジェクトの `.gitignore` に以下を追加することを推奨する。

```
.claude/bash_history
```

利用側プロジェクトの claude-container 向け設定は `.claude-container.d/` ディレクトリに一本化されている。中身は「起動のたび読み込まれるランタイム設定」と「ビルド時にイメージへ焼き込まれる設定」の2種類に分かれる。

```
.claude-container.d/env                  # ランタイム設定（KEY=VALUE、上記「環境変数」参照）。-b 不要、gitignore 対象
.claude-container.d/packages.txt         # apt パッケージ（1行1パッケージ、素のパッケージ名のみの allowlist 検証あり。行頭 # はコメント）。-b 必須、コミット対象
.claude-container.d/requirements.txt     # pip パッケージ（名前＋extras＋バージョン指定子のみの allowlist 検証あり。URL・パス・オプション行・環境マーカー・行内空白は拒否しビルド停止。行内 # 以降はコメントとして剥がされる）。-b 必須、コミット対象
.claude-container.d/allowed-domains.txt  # エグレス制限に追加する許可ドメイン（1行1ホスト名、行頭 # はコメント。起動・更新時の入力検証あり）。-b 必須、コミット対象
.claude-container.d/node-version.txt     # 導入する Node.js のバージョン（例: 22.14.0、1行のみ）。-b 必須、コミット対象
.claude-container.d/codex-version.txt    # 導入する Codex CLI のバージョン（例: 0.154.0、または latest。固定版を推奨、1行のみ）。-b 必須、コミット対象
.claude-container.d/allowed-ports.txt    # エグレス許可を限定するTCPポート（1行1ポートまたはport:port、# はコメント）。-b 必須、コミット対象
.claude-container.d/base-image.txt       # ベースイメージ（例: debian:testing、1行のみ）。-b 必須、コミット対象
```

`env` 以外は任意。`packages.txt`/`requirements.txt`/`allowed-domains.txt` を置かなければ claude-container 同梱のデフォルト（空のフォールバック）が使われる。`allowed-domains.txt` にはプロジェクトの作業に必要な追加ドメイン（例: pip なら `pypi.org` と、パッケージ本体の実ダウンロード先である `files.pythonhosted.org` の両方— index への到達だけでは `pip install` は完走しない）を書く。ビルド時にイメージへ焼き込まれるため、変更を反映するには `-b` での再ビルドが必要（`env` はこのビルド時焼き込みの対象外 — ホスト固有パスをイメージに含めないため）。

`allowed-domains.txt` は前後のスペース・タブと行末 CR を除き、空行と行頭 `#` のコメント行を無視する。各行は ASCII 英数字・ハイフン・ドットで表すホスト名（各ラベル1〜63文字、ラベルの先頭と末尾は英数字、末尾ドットを除き全長253文字以下）とする。大文字、数字で始まる名前、単一ラベル、末尾ドット、punycode 表記は使える。これは DNS ホスト名の書式上の上限である。世代タグを保存する iptables コメントは255バイト以内のため、UNIX時刻が10桁の現在、実際に許可できる名前は末尾ドット込みで233文字までとなる。タグ長は DNS 解決後に検査し、超過した場合は切り詰めず、該当ルールの適用直前に ERROR で拒否する。行内空白・行内コメント・URL・ワイルドカード・アンダースコア・制御文字・NUL は拒否し、複数の名前を空白削除で結合しない。従来は警告だけで継続していた不正な行も起動エラーになるため、既存設定の行内コメントや複数名を含む行は再ビルド前に修正する。ホスト名の書式は全行を検証してから DNS 解決へ渡すため、書式に反する行があると部分的なリストを使わず ERROR になる。起動時は起動を中止し、更新時は警告して次のサイクルへ進む。ホストの `--check` はこの内容検証を行わないため、変更後は `-b` で再ビルドして起動時の検査結果を確認する。

`allowed-ports.txt` は許可ドメイン（GitHub CIDR・`allowed-domains.txt` 指定分）への到達を許すTCPポートを既定の `443,22` から変更したい場合に使う（`jj1xgo/claude-container#31`）。置かなければ `443,22` が使われる（他の3ファイルと異なり WARNING は出ない — `node-version.txt`/`codex-version.txt` と同じ任意機能の流儀）。この制限は許可ドメイン宛のルールにのみ適用され、DNS（53番）とホストネットワーク宛のルールには適用されない（後述「アーキテクチャ」節参照）。`iptables` の `multiport` マッチは最大15枠で、単一ポートは1枠、範囲指定は両端で2枠として数える（範囲内のポート数にはよらない）。例えば単一1件＋範囲7件は15枠で受理し、範囲8件は16枠のため理由付きの ERROR で拒否する。`443` は必ず含めること（api.anthropic.com・api.github.com への到達と起動時の自己検証に必要）、`80` は許可できない（起動時の自己検証が「api.github.com:80 へ到達できない」ことを遮断のプローブに使う）。どちらも範囲指定（`79:81` 等）で含む場合も同様で、違反するとコンテナ起動時に理由付きの ERROR で停止する（`jj1xgo/claude-container#49`）。

各番号は1〜5桁の数字で指定し、6桁以上は先頭ゼロ付きでも書式エラーとする。先頭ゼロは十進数として受理し、iptables へ渡す際に除去する（例: `00443` → `443`、`0120` → `120`）。ポート番号は `1〜65535`、範囲は `1 <= 開始 < 終了 <= 65535` とする。`0`、範囲外の番号、逆順・同値の範囲は起動前のファイアウォール初期化で理由付きの ERROR となる。例えば `443:443` は単一値 `443` に直す。更新モードも同じ検査を行う。ホスト側の `--check` はこのファイルの内容検証を行わないため、変更後は `-b` で再ビルドして起動時の検査結果を確認する。

`node-version.txt` は apt の debian:stable では入手できない Node.js バージョン（例: 22.x — trixie は 20.x、testing は 22 を飛ばして 24.x）が必要な場合に使う。nodejs.org 公式の Linux tarball を取得し、同梱の `SHASUMS256.txt` でチェックサム検証したうえで展開する。**ビルド時ネットワークは無制限のため、`allowed-domains.txt` に `nodejs.org` を追加する必要はない**（`init-firewall.sh` のエグレス制限はランタイムにのみ適用される）。置かなければ Node.js は導入されない（他の3ファイルと異なり、この場合は WARNING も出ない — 新設の任意機能であり、大多数のプロジェクトが使わないのが正常な状態のため）。

`codex-version.txt` は OpenAI の Codex CLI（`@openai/codex`）を諮問・レビュー用のセカンドオピニオンとして導入したい場合に使う。`node-version.txt` と同じ任意のオプトインファイルで、置かなければ導入されず WARNING も出ない。npm 経由でグローバルインストールするため **npm が必要** — `node-version.txt` を併せて設定するか、`packages.txt` に `nodejs`/`npm` を追加すること（npm が無いままバージョンを指定するとビルドがエラーで停止する）。固定バージョン（例: `0.154.0`）の代わりに `latest` と書くと、Claude Code 本体と同じく `-b` リビルドのたびに npm の `latest` dist-tag を再解決してインストールし直す（このケースだけ専用のキャッシュ破棄が働く）。`node-version.txt` は nodejs.org 公式 tarball の SHA256 照合が前提のため `latest` は使えない（バージョン固定のみ）— この非対称は両ファイルの導入方式の違いによるもの。`latest` では上流の変更（サブコマンドの廃止やフラグの変更）が次の `-b` 再ビルドでそのまま入るため、README の手順や利用側プロジェクトの設定が黙って壊れうる（実例: codex-cli は `codex mcp-server` を rust-v0.149.0 で非推奨にし、rust-v0.154.0 で削除した。[`#100`](https://github.com/jj1xgo/claude-container/issues/100)）。手順の安定を要するプロジェクトは固定版を推奨する。コンテナ内からの呼び出し方は後述「Codex CLI をセカンドオピニオンとして使う」節を参照。

`base-image.txt` はベースイメージをホスト環境に合わせたい場合に使う（例: `debian:testing`。内部運用issue参照）。置かなければ既定の `debian:stable` が使われる（他の3ファイルと異なり WARNING は出ない）。許容範囲は **docker.io の debian 公式イメージのみ**（タグは自由、`debian:stable@sha256:<64桁hex>` のような digest pin も可）。範囲外の値は起動を拒否する（fail-closed）。この制限は「セキュリティ境界」ではなく「サポート範囲の宣言・互換性ガード」と位置づけている — `.claude-container.d/` を書き換えられる主体は `packages.txt` 経由で apt の maintainer script をビルド時 root で実行でき、`requirements.txt` 経由の任意 PyPI 名指定でも sdist の `setup.py` がビルド時 root で実行される経路が原理的に残る（PyPI は open publishing のため）。いずれもベースイメージ名だけを縛る防御効果は限定的（Codex 諮問による指摘、内部運用issue参照）。実際の互換性は `Dockerfile.claude` 側のビルド時アサーション（`setpriv`/`tini` の存在・`setpriv --ambient-caps`/`--inh-caps` の受理・apt sources の HTTPS 化）が担保する。ただしこのアサーションは「正直な壊れ方」しか検知できず、悪意を持って `setpriv` 等を偽装するベースイメージは検知できない。`debian:testing`/`debian:sid` のような rolling suite を指定すると、`-b` のたびに未知の apt パッケージ版へ追随するため再現性が下がる — 再現性が必要な場合は日付タグ（`debian:trixie-20260701`）か digest pin を使うこと。値の検証はホスト側の `claude-container` スクリプトが行うため、`podman build` を直接実行する経路では効かない。

## GitHub トークンの配線

設計原則（v4〜、`jj1xgo/claude-container#24`）: **常時使える（export される）権限は最小に、広い権限は明示操作の壁の向こうに、残るリスクは文書で正直に。** GitHub へ書き込む（`gh` CLI・MCP 経由問わず）トークンは、汎用シークレットディレクトリ（`SECRETS_DIR`）1本に集約する。

| スロット | 置き場所 | export | 想定用途・推奨スコープ |
|---|---|---|---|
| メイン PAT | `SECRETS_DIR` 直下（例 `GITHUB_MAIN_PAT`） | されない | push・PR レビュー・Release 作成等。`Contents: write` を含む広い権限を許容する場合はここに置く。コンテナ内では値が環境変数に現れず、`GH_TOKEN=$(cat "$GITHUB_MAIN_PAT_FILE") gh ...` のように都度明示的に読む |
| MCP／issues 用 PAT | `SECRETS_DIR/export/`（例 `GITHUB_MCP_PAT`） | される | GitHub 公式 MCP サーバー・issue 系の自動確認 hook 用。**Issues 限定などスコープを絞ったトークンを推奨**（後述リスク参照） |

**重要**: 「`.claude-container.d/env` を置く場所」と「PATの `Repository access` で選ぶリポジトリ」は別物である。前者はトークンを**使う側**のプロジェクト（例: myproject）、後者は書き込み先リポジトリ（例: claude-container）を指す。myproject から claude-container の Issue に書き込みたい場合、`.claude-container.d/env` は myproject 側に置き、PATの `Repository access` には `claude-container` を選択する — 自分自身（使う側）のリポジトリを登録するわけではない。

fine-grained PAT はトークン単位で、選択した全リポジトリに同一のパーミッションが一律適用される仕様である（リポジトリごとに異なるパーミッションは設定できない）。そのため「自分自身のリポジトリだけ広い権限、他のリポジトリは Issues のみ」としたい場合は、上表のとおりトークンを用途別に分ける。操作系統ごとの可否・パーミッションの全体像は「何ができて何ができないか」節の早見表を参照。

1. GitHub の Settings → Developer settings → Personal access tokens → Fine-grained tokens で新規トークンを作成する。**classic PAT は使わない**（最小の書き込みスコープ `repo` でも全リポジトリのコード読み書きを含んでしまい、漏洩時の被害が過大なため）。設定は用途に応じて選ぶ:
   - Repository access: `Only select repositories` → 書き込み先リポジトリのみ選択（複数選択すると、以下のパーミッションが選択した全リポジトリに一律適用される点に注意）
   - Repository permissions: 必要最小限のみ付与する。MCP／issues 用トークンなら `Issues: Read and write` のみを推奨。メイン PAT に `Pull requests: Read and write` を足すと自リポジトリの PR レビューまで、`Contents: write` を足すと push・PR マージ・Release 作成までコンテナ内から実行可能になる（`Contents: write` を付与しない限り push・マージ・Release作成はホスト側限定のまま維持される）
   - Expiration: 90日以下を推奨
2. ホストにディレクトリを作り（例: `~/.config/claude-container/secrets.d/<project>`）、`chmod 700` する。中に置く各ファイルの**ファイル名がそのままコンテナ内の環境変数名（`export/` 配下のみ）になる**（`^[A-Za-z_][A-Za-z0-9_]*$` に合致しない名前は起動時に WARNING を出してスキップされる）。各ファイルは `chmod 600` し、中身はトークン文字列1行のみ（改行は自動で除去されるが、複数行の値は連結されてしまうため非対応）。各ファイルは実体（通常ファイル）として置くこと — コンテナにはこのディレクトリ単体がマウントされるため、ディレクトリ外を指すシンボリックリンクはコンテナ内でリンク先を解決できず、**警告なしにスキップされる**（既存のトークンファイルを流用したい場合はシンボリックリンクでなく値をコピーする）
3. メイン PAT は `SECRETS_DIR` 直下に置く（例 `SECRETS_DIR/GITHUB_MAIN_PAT`）。MCP／issues 用 PAT は `SECRETS_DIR/export/` 配下に置く（`export/` ディレクトリ自体も `chmod 700`）
4. ターゲットプロジェクトの `.claude-container.d/env` に `SECRETS_DIR=~/.config/claude-container/secrets.d/<project>` のようにパスを書く。`.claude-container.d/env` はホスト固有のパスを含みうるため gitignore 対象であり、そもそもコミットされない
5. ディレクトリが存在しない場合は起動時にエラーで停止する（fail-closed）。ディレクトリが `700` でない、または中のファイルが `600` でない場合は警告が出る

トークンはホスト上のファイルとしてのみ扱われ、コンテナの `environment:` には渡らない（`podman inspect` 等にも露出しない）。メイン PAT はファイルパスのみが `GITHUB_MAIN_PAT_FILE` として export され、値自体は export されない。`export/` 配下のトークンのみ、ファイル名と同名の環境変数として値ごと export される。**既に環境に存在する変数名（`PATH` 等）と衝突する場合は、既存の値を上書きせず警告を出してスキップする**。

これは汎用の環境変数注入機構であり、GitHub トークンに限らず任意のシークレットを持ち込める。持ち込んだ変数はコンテナ内の全プロセス（Claude 本体・hooks・任意の npm スクリプト等）から読めるため、1コンテナに持ち込むのはそのプロジェクトで実際に使う最小本数に留めること。**`export/` に `GH_TOKEN`/`GITHUB_TOKEN` という名前のファイルを置くと `gh` CLI の ambient 認証が復活する**（本設計の意図に反するため非推奨。明示的な opt-in と理解した上でのみ行うこと。同様の理由でコンテナ内での `gh auth login` の実行も推奨しない）。

**設定済みスコープの確認**: **現時点で fine-grained PAT の対象リポジトリ一覧を機械的に取得する手段は存在しない**。GitHub側にも対象リポジトリを一覧で返すAPIは無く（個人アカウント所有リポジトリ向けの同等APIは存在しない。組織所有リポジトリ限定の `GET /orgs/{org}/personal-access-tokens/{pat_id}/repositories` はGitHub App専用でPATでは使えない）、本プロジェクトもPAT設定変更への追従コストを避けるため対象リポジトリ自体を保持しない。したがって個別リポジトリ単位で疎通確認するしかない: `GH_TOKEN=$(cat <トークンファイル>) gh api /repos/<owner>/<repo>` を実行し、**private リポジトリに対してのみ** 200/404 がスコープ判定として機能する（200＝アクセス範囲内、404＝範囲外）。**public リポジトリはこの方法で判定できない**: GitHub は public リポジトリのメタデータ（`GET /repos/{owner}/{repo}` とその `permissions` フィールド）をトークンの `Repository access` 設定に関わらず常に200で返すため、公開リポジトリでは到達可否も `permissions` の値もスコープの証拠にならない（実機検証済み。詳細: `jj1xgo/claude-container#13`）。public リポジトリの実効スコープを確認したい場合は、実際に書き込み操作（`gh issue create` 等）を試すか、PAT設定画面（Web UI）の `Repository access` 一覧を直接確認すること。対象範囲の正本は常にPATの `Repository access` 設定側にある。

**トークンの更新**: 期限が近づいたら GitHub 側でトークンを再生成し、対応するファイルの中身を新しい文字列で上書きするだけでよい。ビルド時に焼き込まれる設定ではなくランタイムマウントなので、リビルド（`-b`）は不要 — 次回起動時に読み直される。

**注意**: 起動時のチェックはファイルの存在とパーミッションのみで、トークン自体が期限切れかどうかは検証しない。期限切れのトークンが入っていてもコンテナは正常に起動し、実際に `gh` コマンドで GitHub API を呼んだ時点で初めて認証エラーになる。気づかず放置しないよう、設定した `Expiration` をどこかにメモしておくこと。

**GitHub 公式 MCP サーバーを使う場合のレシピ**: `gh` CLI でなく MCP 経由で GitHub を操作したい場合、次のように設定する。

1. ターゲットプロジェクトの `.claude-container.d/allowed-domains.txt` に `api.githubcopilot.com` を追加する（ビルド時焼き込みのため `-b` での再ビルドが必要）
2. `SECRETS_DIR/export/` に PAT ファイルを置く（例: ファイル名 `GITHUB_MCP_PAT`。**Issues 限定などスコープを絞ったトークンを推奨** — MCP サーバーのツール一覧には push・PR マージ・Release 作成等の書き込みツールも含まれており、広いスコープのトークンを渡すとそれらが実効化してしまうため）
3. ターゲットプロジェクトの `.mcp.json` に以下のように書く（Claude Code は `${VAR}` を環境変数から展開する）:
   ```json
   {
     "mcpServers": {
       "github": {
         "type": "http",
         "url": "https://api.githubcopilot.com/mcp/",
         "headers": {
           "Authorization": "Bearer ${GITHUB_MCP_PAT}"
         }
       }
     }
   }
   ```

GitHub 公式リモート MCP サーバーの既定の認証は OAuth（ブラウザでのログイン）だが、headless なコンテナ内ではブラウザを開けないため、上記のような PAT を `Authorization` ヘッダで渡す方式が現実的な選択肢になる。なお hooks 等のシェルスクリプトによる自動化は MCP サーバーを呼び出せない（MCP は Claude が使うツールであり、shell から直接叩けるものではない）ため、gh CLI の同梱自体は MCP 導入後も維持している。

**二次防御（`permissions.deny`）**: MCP のトークンスコープを絞っていても、将来広いトークンへ差し替えられた場合に備え、対象プロジェクトの `.claude/settings.json` に write 系 MCP ツールの `permissions.deny` を設定することを推奨する:
```json
{
  "permissions": {
    "deny": [
      "mcp__github__push_files",
      "mcp__github__merge_pull_request",
      "mcp__github__pull_request_review_write",
      "mcp__github__create_or_update_file",
      "mcp__github__delete_file"
    ]
  }
}
```
一次防御は PAT スコープ（issues 限定なら書き込みツールはサーバー側で 403 になる）。deny は二次の多層防御であり、MCP サーバー側の将来のツール追加に対しては fail-open（新設ツールは自動では塞がれない）である点に注意。issue 系ツール（`issue_write`・`add_issue_comment`・read/list/search 系）は通常どおり使えるよう deny 対象から外すこと。

**v3 以前からの移行**: `GH_TOKEN_FILE`・`GH_TOKEN_SECONDARY_FILE`・`SECRETS_DIR/noexport/` は v4 で撤廃された（後方互換なし）。

| 旧 | 新 |
|---|---|
| `GH_TOKEN_FILE` | `SECRETS_DIR` 直下（例 `GITHUB_MAIN_PAT`） |
| `GH_TOKEN_SECONDARY_FILE` | `SECRETS_DIR/export/`（例 `GITHUB_MCP_PAT`） |
| `SECRETS_DIR/noexport/GIT_PUSH_TOKEN` | `SECRETS_DIR/GITHUB_MAIN_PAT`（push・PR用トークンに統合） |

legacy 変数が設定されたまま起動すると fail-closed で停止し、上記の移行手順が起動ログに表示される。実体ファイルを削除・移動する前に、他プロジェクトから同じファイルを参照していないか必ず確認すること（削除は本移行のスコープ外 — 参照確認が済むまで残す）。

**git push を使う場合（`SECRETS_DIR/GITHUB_MAIN_PAT`）**: デフォルトでは git のリモート操作のうち push は不可（後述「何ができて何ができないか」節）。メイン PAT に `Contents: write` を付与すると有効化できる。

1. GitHub の Fine-grained PAT を作成する。Repository access は push 先リポジトリのみに限定し、Repository permissions で `Contents: Read and write` を付与する（push には `Contents: write` が必要）。GitHub 側の branch protection（レビュー必須化・force-push 禁止等）の併用を推奨する
2. トークン文字列を `SECRETS_DIR/GITHUB_MAIN_PAT`（直下、export されない）という名前のファイルに保存し `chmod 600` する
3. ターゲットプロジェクトの `.claude-container.d/env` に `SECRETS_DIR=...` を設定する（他用途で設定済みなら追加設定不要）
4. `Dockerfile.claude` の変更を伴うため `-b` での再ビルドが必要

起動すると `entrypoint.sh` が `SECRETS_DIR/GITHUB_MAIN_PAT` の存在を検知し `GIT_ASKPASS` を自動設定する（トークンの値自体は export されない。パスのみ `GITHUB_MAIN_PAT_FILE` として export される）。以降、対象リポジトリへの `git push`（**HTTPS リモート限定** — SSH リモートには効かない）は、`git-askpass.sh` がトークンをファイルから都度読んで応答するため、追加の手動操作なしに通る。`git-askpass.sh` は github.com 宛の Username/Password プロンプトにのみ応答する fail-closed 設計で、他ホスト・想定外のプロンプトには応答しない。

このトークンは private リポジトリの fetch/pull にも有効になる（`Contents: Read` 相当を含むため）副作用がある点に注意。また `Contents: write` を持つ同じトークンは `GH_TOKEN=$(cat "$GITHUB_MAIN_PAT_FILE") gh pr merge ...` のように gh CLI からも使えてしまうため、push だけでなく PR マージも「できるが、黙ってはできない」（明示読みという一手間を要する）状態になる点を理解した上で運用すること。

`GITHUB_MAIN_PAT` を検知すると、`entrypoint.sh` は `GIT_CONFIG_*` 環境変数で `credential.helper` を空にリセットする。これは、`GITCONFIG_FILE`（後述）でマウントしたホストの gitconfig に `credential.helper = store` 等の設定が含まれていても、`git-askpass.sh` が都度読んだトークンを `~/.git-credentials` へ平文で永続化させないための対策（マウントされる `~/.gitconfig` は read-only のため `git config --global` での上書きはできず、全 config ファイルより後に適用される `GIT_CONFIG_*` 環境変数がこの目的で使える唯一の手段）。

**force push 対策**: `GITHUB_MAIN_PAT` はコンテナ内からの `git push --force` 等の強制上書きも素通しするため、対象プロジェクトの `.claude/settings.json` に `permissions.deny` で `Bash(git push --force:*)` を追加するのが一次防御になる。ただしこの deny はコマンド文字列の前方一致で判定されるため、フラグ後置形（`git push origin master --force`）・`git -C <path> push --force`・`+refspec` 形式（例: `git push origin +feature:main`）は素通しする既知の限界がある。`--force-with-lease` は `--force` で始まらない別オプションのため `Bash(git push --force-with-lease:*)` を別途追加する必要がある。この見逃し範囲を deny ルールの列挙だけで完全に塞ぐのは煩雑なため、「force push はユーザーの明示承認後のみ」という CLAUDE.md 等の文書ルールを二重の防波堤として併用することを推奨する（利用側プロジェクトでの実機検証を踏まえた知見）。

**コンテナ内 git commit（`GITCONFIG_FILE`）**: ホストで `git config --global user.name`/`user.email` を設定していても、デフォルトではコンテナ内に反映されず `git commit` が `Author identity unknown` で失敗する。`.claude-container.d/env` に以下を書くと解消する。

```
GITCONFIG_FILE=~/.gitconfig
```

- 未設定なら従来どおり（`git commit` が `Author identity unknown` で失敗するだけで、他への影響はない）
- 設定した場合、指定ファイルが存在しなければ起動時にエラーで停止する（fail-closed）。存在しないパスをそのまま bind mount すると、ホスト側にその名前の空ディレクトリが誤って作られてしまう問題を避けるため
- read-only マウントのため、コンテナ内から `git config --global` で書き換えることはできない。編集は常にホスト側で行う（ランタイムマウントなので `-b` 再ビルドは不要、次回起動時に反映される）
- `.gitconfig` に `credential.helper` や `include.path` でホスト固有の別ファイルを参照する記述があっても、`git commit` 自体には影響しない（参照先が無ければ黙って無視される、または認証操作時に警告が出る程度）。気になる場合は `user.name`/`user.email` のみを書いた専用ファイルを別途用意し、そちらのパスを `GITCONFIG_FILE` に指定するとよい
- `GITCONFIG_FILE` を設定しても反映されない場合、`/workspace`（起動時に指定したターゲットプロジェクト）自身の `.git/config` に `user.name`/`user.email` が設定されていないか確認する。git の設定優先順位（local > global）により、マウントした `~/.gitconfig`（global 相当）より対象プロジェクトのローカル設定が優先されてしまう

**venv 等の言語ランタイム成果物は必ずコンテナ内で作成する。** ホスト側で `python3 -m venv` 等を実行してターゲットプロジェクト配下に作った場合、生成されるスクリプトのシェバン（例: `venv/bin/pip` の1行目）にホストの絶対パス・ユーザー名（例: `/home/alice/myproject/venv/bin/python3`）が焼き込まれる。同じディレクトリはコンテナ内では `/workspace` 配下・ユーザー `node` としてマウントされるため、そのパスは解決できずシェバン経由の実行（`./venv/bin/djlint` 等）が失敗する（`venv/bin/python3 -m djlint` のように venv 内の python3 をモジュール起動すれば回避できる。素の `python3` はシステム Python で venv の site-packages を見ないため不可）。venv はコンテナを起動してからその中で作成すること。

## MCP サーバーの追加

`.mcp.json` は claude-container が用意する機構ではなく、Claude Code 本体が標準で持つ「プロジェクトルート（`/workspace` 直下）の `.mcp.json` を project-scoped server として自動読み込みする」機能である。そのためタイプ（http／stdio）に応じて、以下の範囲は**claude-container 側を一切変更せず利用側プロジェクトの設定だけで追加できる**。

**http／sse タイプ**（リモートエンドポイントに直接接続するサーバー。例: GitHub 公式 MCP サーバー、具体的な設定例は前述「GitHub トークンの配線」節の「GitHub 公式 MCP サーバーを使う場合のレシピ」を参照）:

1. ターゲットプロジェクト直下に `.mcp.json` を置く（Claude Code が自動で読み込む）
2. 認証が必要なら `SECRETS_DIR/export/` に任意の名前でトークンファイルを置き（前述「GitHub トークンの配線」節参照）、`.mcp.json` 側で `${変数名}` として参照する
3. 接続先ドメインを `.claude-container.d/allowed-domains.txt` に追加する（ビルド時焼き込みのため `-b` での再ビルドが必要）

**stdio タイプ**（コンテナ内でコマンドとして起動するサーバー）は、この一存では追加できない。`entrypoint.sh` が起動時に `/workspace/.mcp.json` を監査し、`command` フィールドを持つサーバーを検知するとサーバー名・実行コマンドを表示した上で対話確認（TTY 入力）を求める。確認できない場合（非対話起動、または拒否）は起動を中止する（fail-closed）。

この確認を挟む理由: stdio タイプのサーバーは、`npx` 等によるネットワーク越しの取得を経ずリポジトリに同梱されたコードとして実行できるため、http タイプと違ってファイアウォール・再ビルドという既存の壁を通らない。`--dangerously-skip-permissions` 下では Claude Code 本来の MCP 承認プロンプトも機能しないため（後述「セキュリティモデル」節）、この対話確認が唯一の壁になる。**環境変数による opt-out は用意していない**: `.claude-container.d/env` はリポジトリ自身が書けるファイルであり、そこで受け付けるキー（前述「環境変数」節の表）に opt-out 変数を加えれば悪意あるリポジトリも同じ行を書けてしまうため、ゲートとして意味を成さない。

stdio タイプのサーバーをどうしても使いたい場合は、`npx` 等の実行時取得（＝セッション開始のたびネットワーク越しに未検証のコードを取得する経路）でなく、`.claude-container.d/packages.txt` 等によるビルド時焼き込み、またはホスト側インストール＋bind mount（`EXTRA_MOUNT` 等）で導入することを推奨する。**`packages.txt` 経路ではバージョン固定ができない**（`pkg=version` 形式のバージョンピンは allowlist 検証で拒否される）ため、バージョン固定が必要な場合は bind mount 経路を採ること。あわせて、npm レジストリ（`registry.npmjs.org` 等）を `allowed-domains.txt` へ追加しないこと — 追加すると `npx` 経由の実行時取得が成立し、上記の対話確認を毎回強制されるだけでなく、取得するコード自体の検証が効かなくなる。

**TOFU（Trust On First Use）による確認の省略**（claude-container#28）: 対話確認で `y` と回答すると、`claude-container` スクリプトが承認時点の stdio サーバー定義のハッシュを、ホスト側 `~/.local/state/claude-container/mcp-approvals/<project>` に記録する（`.mcp.json` 自体やコンテナ内には保存しない — コンテナ側から改変できない場所に置くのが目的）。次回以降の起動では、`.mcp.json` の stdio サーバー定義がこの記録と一致する限り対話確認を自動的にスキップし、定義が変化した場合のみ再度確認を求める。記録はプロジェクトごとに独立しており、`--clean <directory>` で当該プロジェクト分のみ、引数なしの `--clean` で全プロジェクト分をまとめて削除できる。

なお `claude mcp add` によるローカル／ユーザースコープの登録（`~/.claude.json` 側）はこのゲートの対象外である。これはリポジトリ側が制御できないファイルへの登録のため「悪意あるリポジトリの初回起動」という脅威モデルには当てはまらず、各プロジェクトの利用者が自己管理する範囲になる。

## Codex CLI をセカンドオピニオンとして使う

OpenAI の Codex CLI をコンテナ内の Claude Code セッションから諮問・レビュー用のセカンドオピニオンとして呼ぶ場合のレシピ。Codex は `codex exec`（非対話 CLI）として呼び出す。以前はここに Codex を stdio 型 MCP サーバー（`codex mcp-server`）として `.mcp.json` に登録する手順を載せていたが、上流の codex-cli が rust-v0.149.0 で `codex mcp-server` を非推奨にし、rust-v0.154.0（2026-09-09、[openai/codex#42993](https://github.com/openai/codex/pull/42993)）で削除したため、MCP 経路は案内しない（0.153.0 以前に固定すれば動くが非推奨経路のため推奨しない。[`#100`](https://github.com/jj1xgo/claude-container/issues/100)）:

1. ターゲットプロジェクトの `.claude-container.d/codex-version.txt` に導入したい Codex のバージョン（例: `0.154.0`。固定版を推奨）または `latest` を書く（前述「利用側プロジェクトの設定」節）。npm が必要なため `node-version.txt` も併せて設定する
2. ターゲットプロジェクトの `.claude-container.d/allowed-domains.txt` に `chatgpt.com` を追加する。ChatGPT アカウント認証（`auth.json`）を使う Codex は API 呼び出し先を `https://chatgpt.com/backend-api/` にハードコードしており（[openai/codex](https://github.com/openai/codex) `codex-rs/model-provider-info/src/lib.rs` の `CHATGPT_CODEX_BASE_URL` 等）、許可しないとエグレスファイアウォールに阻まれて呼び出しが失敗する
3. ホストに Codex 専用の認証情報ディレクトリを用意し、`~/.codex/auth.json`（ホストで `codex login` 済みのもの）を1回だけシードコピーする。**ホストの実 `~/.codex` を `CODEX_DIR` にそのまま指定しないこと** — auth.json の自動リフレッシュ書き戻しのため rw マウントが必須であり、実ディレクトリを共有するとコンテナ側のコードが `config.toml`（`notify` フック等）を書き換えられ、ホストで Codex を起動した際に任意コマンドが実行される経路になる（詳細は `.claude-container.d/env.example` の該当コメント参照）:
   ```
   mkdir -p -m 700 ~/.codex-container
   cp ~/.codex/auth.json ~/.codex-container/auth.json
   chmod 600 ~/.codex-container/auth.json
   ```
4. ターゲットプロジェクトの `.claude-container.d/env` に `CODEX_DIR=~/.codex-container` を設定する（`-b` 不要、ランタイムマウント）
5. コンテナ内の Claude Code セッションから、通常のコマンドとして呼ぶ（`.mcp.json` には登録しない）:
   ```bash
   codex exec --sandbox read-only -C /workspace "<依頼文>"
   ```
   `--sandbox read-only` は省略しない（呼び出し時の `--sandbox` が `config.toml` の値に勝つ。諮問・レビュー用途は読み取り専用で足りる）。`-C /workspace` で作業ルートを明示する（Codex は作業ルートの `AGENTS.md` を指示として読むため、起点を固定する）。最終応答だけをファイルに取りたい場合は `-o <ファイル>` を足す。`/workspace` が git リポジトリでない場合は `--skip-git-repo-check` が必要
6. `-b` での再ビルドが必要（`codex-version.txt`/`allowed-domains.txt` はいずれもビルド時焼き込み設定のため）

**運用上の注意**: Codex は作業ルートの `AGENTS.md` を指示として読む。MCP 経路では `cwd` の渡し忘れで意図しない `AGENTS.md` が拾われる問題があった（[openai/codex#12128](https://github.com/openai/codex/issues/12128)）。`codex exec` でも起点が変われば同じことが起きるので、`-C /workspace` を毎回明示する運用を徹底すること。また auth.json のリフレッシュフローには既知の不具合報告（[openai/codex#15502](https://github.com/openai/codex/issues/15502)）があり、この領域は枯れていない可能性がある点に留意する。

## アーキテクチャ

主要ファイルが連携して動作する。

- **`claude-container`**（bash）— エントリーポイント。絶対パスを解決し、ターゲットプロジェクトのディレクトリ名（basename）をサニタイズした文字列に絶対パスの sha256 先頭8文字を付与した `PROJECT_NAME` を算出する（例: `myproject-3f2a9c1b`）。これによりイメージ名（`localhost/<PROJECT_NAME>_claude-auth-workspace`）とビルドコンテキストのステージング先（`.build-context/<PROJECT_NAME>/`）をプロジェクトごとに分離し、`podman compose -p "$PROJECT_NAME"` でプロジェクト名を明示する。以前は全プロジェクト共通の固定イメージ名・固定ステージング先だったため、異なるプロジェクトを交互にビルドすると後勝ちで上書きされる問題があった。`.claude-container.d/env` の `KEY=VALUE` 行のうち許可リストのキーだけを読み込み、`TZ` を自動検出した上で `CONTEXT` / `CLAUDE_CONTAINER_DIR` を設定して `podman compose run` に委譲する（`--env-file /dev/null` を付け、対象プロジェクト直下の `.env` は補間に使わない）。`-b` 指定時は `podman compose build` を `run` とは別ステップで実行する — `run --build` はビルド失敗時に既存の古いイメージへフォールバックしてしまう（fail-open）ため、分離して失敗時は起動へ進ませない（fail-closed）。ビルド前に、プロジェクト側の `.claude-container.d/packages.txt`・`requirements.txt`・`allowed-domains.txt`（無ければ claude-container 同梱のデフォルト）・`node-version.txt`・`codex-version.txt`・`allowed-ports.txt`（無ければ空ファイルを都度生成。他の3ファイルと異なり同梱のデフォルトファイルは持たず、WARNING も出さない）と `entrypoint.sh`・`init-firewall.sh`・`git-askpass.sh`・`validate-build-input.sh`・GitHub meta スナップショット（後述）をこのプロジェクト専用の `BUILD_CONTEXT_DIR` に集約する（`-b` 指定時、またはイメージ未ビルド時のみ実行）。`--clean <directory>` はそのプロジェクト分のイメージ・ネットワーク・ビルドコンテキストのみを、`--clean`（引数なし）は実在する claude-container イメージ全てを走査して全プロジェクト分を削除する（レガシーの単一共有イメージ `localhost/claude-container_claude-auth-workspace` も同じ命名パターンで検出されるため、旧バージョンからの移行時は `--clean` の実行だけで回収できる）。
- **`compose.yml`** — サービス `claude-auth-workspace` を定義。ビルドコンテキストは `${BUILD_CONTEXT_DIR}`（上記でステージングされたディレクトリ）、Dockerfile は `${CLAUDE_CONTAINER_DIR}/Dockerfile.claude` を参照する。ホストの `~/.claude.json` と `~/.claude/`（認証・設定）、対象ワークスペース（`/workspace`）、`/etc/localtime`（タイムゾーン）をマウントする。`userns_mode: keep-id` でコンテナ内ファイルのオーナーをホストユーザーに合わせる。`cap_add` で `NET_ADMIN`/`NET_RAW` を付与し、`init-firewall.sh` がコンテナのネットワーク名前空間に iptables ルールを設定できるようにする（rootless podman + `userns_mode: keep-id` ではこれらが非root ユーザー `node` の ambient set にも入り全子プロセスへ継承されるため、`Dockerfile.claude` の `ENTRYPOINT`（次項）で剥奪する。後述「セキュリティモデル」節参照）。既定の `sysctls` は `net.ipv6.conf.{all,default}.disable_ipv6=1` で IPv6 を無効化する。IPv6 を明示的に有効にした場合は `compose.ipv6.yml` でネットワークと sysctl を切り替える（「IPv6 を任意で有効にする」参照）。ホストで install した plugin をコンテナ内で読み込めるよう、`compose.plugins-alias.yml` でホストの `~/.claude/plugins` をホストと同じ絶対パス（例 `/home/<host user>/.claude/plugins`）にも `:ro` で重ねる（`claude-container` の `guard_plugins_alias()` が条件を満たすときだけ追加する固定 override。後述「何ができて何ができないか」節の plugin の項と「セキュリティモデル」節の限界 (7) を参照。[`#98`](https://github.com/jj1xgo/claude-container/issues/98)）。`SHARED_MOUNT_HOME_ALIAS=1` のときは `compose.shared-home.yml`（`~` 配下の同じ相対位置）と `compose.shared-host.yml`（ホストと同じ絶対パス）で `SHARED_MOUNT` の実体を `:ro` で重ね、`AGENTS_DIR` のときは `compose.agents.yml` で `/home/node/.agents` に `:ro` で付ける（いずれも `claude-container` の `guard_shared_home_alias()`・`guard_agents_dir()` が値を検証したときだけ追加する固定 override。前述「ホストの指示ファイルとスキルをコンテナ内で解決する」節。[`#99`](https://github.com/jj1xgo/claude-container/issues/99)）。`CODEX_DIR` を設定した場合は Codex CLI の認証情報ディレクトリを rw でマウントする（他のオプトインマウントと異なり `:ro` を付けない — auth.json のトークンリフレッシュ書き戻しのため。前述「Codex CLI をセカンドオピニオンとして使う」節参照）。
- **`Dockerfile.claude`** — 既定 `debian:stable`（`.claude-container.d/base-image.txt` で上書き可、前述「利用側プロジェクトの設定」参照。`FROM` は `COPY` より先に評価されるためファイルを直接読めず、`ARG BASE_IMAGE` 経由で受け取る）をベースにビルド。`ca-certificates` を HTTP でインストール後、apt ソースの全 URI を HTTPS に書き換えてから残りのパッケージを取得する（ホスト名リテラルではなく結果ベースで書き換えるため、ミラーが異なっても無言で no-op にならない）。固定 apt レイヤーの直後に、ベースイメージ可変化に伴うビルド時アサーション（`setpriv`/`tini` の存在・`setpriv --ambient-caps`/`--inh-caps` の受理・apt sources に `http://` が残っていないこと）を fail-closed で実行し、境界機構の土台が壊れたまま静かにビルドが成功する事態を防ぐ。Claude Code は公式 native installer（`curl -fsSL https://claude.ai/install.sh | bash`）でインストール。非 root ユーザー `node`（UID 1000、明示的に作成）で動作し、`CMD ["/usr/local/bin/entrypoint.sh"]`（次項参照。root 所有の `/usr/local/bin` に境界アセットとして配置され、node からは書き換えられない）を実行する。`node:24`（約 1.1 GB）から切り替えた理由: native installer は glibc のみ依存で実行時に Node.js を必要としないため、軽量な Debian ベースで十分。slim ではなく full 版を使う理由: full 版には `ca-certificates` 等の基本パッケージが含まれており apt 周りの初期設定が最小限で済む。`ENTRYPOINT` は `setpriv --ambient-caps=-all --inh-caps=-all /usr/bin/tini --` で、`tini` の起動前に ambient/inheritable capability を全プロセスツリーから剥奪する（`setpriv` は exec するため居残らず、tini は PID1 のまま）。これにより `compose.yml` の `cap_add` が非root ユーザーの ambient set にも入る問題（前項参照）を打ち消し、`NET_ADMIN`/`NET_RAW` の実消費者を `sudo` 経由の `init-firewall.sh`（root、bounding set 由来）のみに限定する。tini を PID1 に据えるのは、claude 自身が PID1 だと、PID1 に再親付けされた子プロセス（ファイアウォール更新ループの sudo 補助プロセス等）が reap されずゾンビとして蓄積し、さらに claude が終了時にハングした場合（2026-07-02 に実障害: ホストカーネルの workqueue Oops により kill 不能な D 状態スレッドが残存）は PID1 自体が reap 不能なゾンビとなり、crun がシグナルを配送できず（`crun kill ... failed` / "No such process"）`podman stop` でもコンテナを回収できなくなる。tini を PID1 に置くことで reap と `podman stop` が機能し続ける（カーネル側のハング自体は tini でも防げない）。`tini` は `packages.txt` に入れず Dockerfile 固定のパッケージ行に含める — プロジェクト側 `.claude-container.d/packages.txt` で上書きされて消えるのを防ぐため。`node-version.txt` ブロックの直後には、同じ任意オプトインの流儀で Codex CLI（`@openai/codex`）を npm 経由で導入するレイヤーがある（`codex-version.txt` で指定、npm 不在時はビルドをエラーで止める。詳細は内部運用issue参照）。`packages.txt`/`requirements.txt` の取り込みも `validate-build-input.sh` による allowlist 検証を `apt-get`/`pip3` の実行より前に置く同格の fail-closed 検証で、setpriv/tini アサーションと同じく境界機構の土台が壊れたまま静かにビルドが成功する事態を防ぐ（前述「利用側プロジェクトの設定」参照）。
- **`entrypoint.sh`** — コンテナの `CMD`（PID1 は上記 tini、このスクリプトと `exec` 先の claude はその子として動く）。起動時に `init-firewall.sh` でエグレス制限を適用し（失敗時は起動を中断）、バックグラウンドでドメイン再解決ループ（約15秒間隔、次項参照）を開始したうえで `claude --dangerously-skip-permissions` を起動する。あわせて `/workspace/.mcp.json` を監査して stdio タイプの MCP サーバーを検知した場合は対話確認を要求する（fail-closed。詳細は「MCP サーバーの追加」節参照）。
- **`init-firewall.sh`** — コンテナ起動時に root（sudo）で実行されるエグレス制限スクリプト。Anthropic 公式 devcontainer の同名スクリプトの移植で、iptables により「許可したドメイン以外への外向き通信を遮断」する（deny-by-default）。Claude Code に必要なエンドポイント（api.anthropic.com・GitHub 等）とプロジェクト指定の `allowed-domains.txt` のみ許可する。許可ドメイン宛のルール（GitHub CIDR・タグ付きドメインルール）はさらに TCP ポートを `allowed-ports.txt` で指定した範囲（既定 `443,22`）へ限定する（`jj1xgo/claude-container#31`）。この制限は許可ドメイン宛のルールにのみ適用され、DNS（53番、指定リゾルバ限定）とホストネットワーク宛のルール（ゲートウェイ単一IPのみ許可、`/24` 全体ではない）は対象外（それぞれ別の理由でスコープが絞られているため）。GitHub IP レンジは起動時にライブ取得せず、ビルド時に焼き込まれたスナップショットを読み込むだけ（詳細は下記「GitHub meta スナップショット」参照）。設定後に example.com へ到達**できない**こと・api.github.com / api.anthropic.com へ到達**できる**こと・許可ドメイン上の非許可ポート（api.github.com:80）へ到達**できない**ことを自己検証する（GitHub 側は API クォータを消費しない TCP 接続確認）。失敗時はコンテナを起動しない（fail-closed）。ただし、許可ドメイン（`allowed-domains.txt` 指定分を含む）が恒久的に存在しない場合（NXDOMAIN）は警告に留め起動を継続する（一時的な解決失敗は従来どおり fail-closed）。DNS の A 応答が `0.0.0.0/8`・`127.0.0.0/8` の場合も、警告してその IP の追加・更新をスキップし、それだけでは起動を失敗させない。同じ応答内の他の IP や次のドメインは処理を続ける。既存の該当ルールは通常の約3分の猶予期間を経て削除する。DNS が返した private / link-local には、内部ホストの明示的な許可に使うため従来どおり許可ルールを追加する。loopback・ホストゲートウェイの別ルールによる許可も維持する。既定の IPv4 モードでは IPv6 を `compose.yml` の `sysctls` で無効化するのが主対策だが、それが効かない環境向けに本スクリプト自身も `/proc/sys/net/ipv6/conf/*/disable_ipv6` への書き込みをフォールバックとして試みる（失敗しても警告のみで起動は継続する）。いずれの結果にかかわらず、既定モードの `ip6tables` による IPv6 全遮断は最終防衛線として維持する。IPv6 有効時は専用の `ipv6-firewall.py` が AAAA と IPv6 CIDR の許可リストを管理し、この全遮断処理は実行しない。許可ドメインの IP は `entrypoint.sh` が起動するバックグラウンドループにより約15秒間隔で再解決され（`init-firewall.sh --refresh-domains`）、新しい IP を差分追加・約3分間見つからない IP を個別削除することで、CDN の短い TTL による IP ローテーションに追従する（チェーン全体のフラッシュは行わないため、更新中に新規接続が失敗する窓は作らない）。
- **`validate-build-input.sh`** — `packages.txt`/`requirements.txt` の正規化・照合を担う POSIX sh スクリプト。ビルド時（`Dockerfile.claude` の `RUN`）・起動前診断（`--check`）・テスト（`test-build.sh`）の3者が同じスクリプトを呼ぶことで、検証ロジックが複数箇所へ複製されドリフトする事態を防ぐ（`claude-container#34`）。責務は正規化と照合のみで、インストール・ネットワークアクセスは行わない。
- **`packages.txt`** / **`requirements.txt`** / **`allowed-domains.txt`** — claude-container 同梱のデフォルト apt/pip パッケージ・許可ドメイン一覧（フォールバック既定値）。プロジェクト側で上書きする場合は `.claude-container.d/` を使う（「利用側プロジェクトの設定」参照）。`node-version.txt`・`allowed-ports.txt` にはこの種の同梱デフォルトは無く、プロジェクト側に無ければ `claude-container` がビルドコンテキスト内に空ファイルをその場で生成する（前者は Node.js 未導入、後者は `init-firewall.sh` 自身が既定値 `443,22` を適用する、という意味。いずれも警告は出さない）。`codex-version.txt` も同じ扱い（Codex CLI 未導入、警告なし）。

### GitHub meta スナップショット

`init-firewall.sh` の許可リストが使う GitHub IP レンジは `https://api.github.com/meta` から取得する。未認証 GitHub API のレート制限（60 req/h/IP）を避けるため、取得は `claude-container` のビルドコンテキスト準備時（`-b` のたび通常1リクエスト、一時エラー時は最大3試行）に1箇所だけで行い、`Dockerfile.claude` がその結果をイメージへ焼き込む。コンテナ起動のたびのライブ取得は行わないため、何度再起動してもレート制限は消費しない。取得に失敗した場合は (1) このプロジェクトの前回ステージング分（`.build-context/<PROJECT_NAME>/` に残っている）、(2) それも無ければ他プロジェクトの最新スナップショット（GitHub の IP レンジは変更頻度が低いため実用上問題ない）を警告付きで再利用し、いずれも無い場合のみビルドを中断する。

### 起動・ビルド準備の通信待ち時間

GitHub meta の取得はランチャー・`test-build.sh` ともに、接続10秒、1試行30秒、
再試行2回まで（接続拒否と curl が一時的と判断するエラーが対象）とする。
再試行の開始は最初の試行から60秒まで、`Retry-After` の待機も含めて外側の
`timeout` が90秒で終了させる。終了しなければ5秒後に強制終了する。
通常の小さな JSON 取得には余裕を持たせつつ、通信不調時に数分以上待ち続けない値とした。
`--max-time` は試行ごとにリセットされ、`--retry-max-time` は進行中の試行を止めないため、
[全体を別に制限する](https://curl.se/docs/manpage.html#--retry-max-time)。
部分応答は一時ファイルに受け、取得と JSON 検証が成功した場合だけ保存先を更新する。
Ctrl-C は取得処理にも伝え、中断時も一時ファイルを清掃する。
失敗時は終了コード（curl の28はタイムアウト、timeout の124は全体上限）と上限をログに残し、
上記のスナップショット再利用へ進む。`test-build.sh --build-only` は再利用元もなければ77（not run）。

IPv4 起動時の HTTPS 自己検証は、禁止先 `example.com` が接続5秒・全体10秒、
許可先 `api.anthropic.com` が接続10秒・全体20秒で、再試行しない。
許可先でタイムアウトしても検証失敗として起動を停止する。
禁止先の通信失敗を期待する従来の判定は維持するため、これだけでは相手側の障害と遮断を区別できない。
実コンテナ CI は前後の対照通信でこの区別を補う。
これらの curl 呼び出しは `-q` で利用者の `.curlrc` を読み込まず、上限と再試行を固定する。
ビルド全体（apt 等）や DNS 更新全体の所要時間を制限する設定ではない。

## イメージの変更

`Dockerfile.claude` を編集して `./claude-container -b /path/to/project` でリビルドする。`-b` を付けると GitHub meta スナップショットの再取得（上記）が試みられ、あわせて `CACHEBUST` にその時点のエポック秒が渡されて install レイヤーのキャッシュが必ず破棄される。これにより、`-b` のたびに `install.sh` が再実行されて最新版の Claude Code が取得される（apt パッケージ等の上位レイヤーはキャッシュを流用するため高速）。再現性が必要な場合は `CLAUDE_CODE_VERSION=1.2.3 ./claude-container -b /path/to/project` のようにシェル環境で固定する（`.claude-container.d/env` は許可リスト外のため無視される。理由は [`#62`](https://github.com/jj1xgo/claude-container/issues/62)）。

`.claude-container.d/` のパッケージ一覧・許可ドメイン（`allowed-domains.txt`）・許可ポート（`allowed-ports.txt`）・Node バージョン指定（`node-version.txt`）・ベースイメージ指定（`base-image.txt`）を変更した場合も、イメージへ反映するには `-b` での再ビルドが必要。`entrypoint.sh`・`init-firewall.sh`・`git-askpass.sh`・`validate-build-input.sh`・`Dockerfile.claude` 自体などビルドコンテキストへステージされるスクリプトの変更も同様（前述「アーキテクチャ」節参照）。

`.build-context/` は claude-container リポジトリ直下に生成されるビルドコンテキストの生成物（`.gitignore` 対象）で、プロジェクトごとに `.build-context/<PROJECT_NAME>/` のサブディレクトリへ分離される。`./claude-container --clean /path/to/project` でそのプロジェクト分のみ、`./claude-container --clean`（引数なし）で全プロジェクト分をまとめて削除できる。

Claude Code の自動アップデートは `compose.yml` の `DISABLE_AUTOUPDATER: "1"` で無効化している。コンテナは `--rm` で起動するためアップデートを取得しても終了時に消えるためで、バージョン更新は `-b` でのリビルドで行う。

## コンテナ間の永続化

コンテナは `--rm` で起動するため終了時に内部の状態は消えるが、以下の常時マウントはホストに bind mount されているため**コンテナを再起動しても保持される**（`EXTRA_MOUNT`/`SHARED_MOUNT`/`SECRETS_DIR` 等の opt-in マウントは、設定した本人がホスト側に同じパスを維持する限り同様に保持されるが、任意設定のためここには含めない — 一覧は「環境変数」節参照）。

| コンテナ内パス | ホスト側 | 内容 |
|---|---|---|
| `/home/node/.claude/` | `~/.claude/` | Claude のメモリ・設定・セッション履歴 |
| `/home/node/.claude.json` | `~/.claude.json` | Claude の認証情報 |
| `/workspace/` | 起動時に指定したディレクトリ | 作業対象プロジェクト |

## 何ができて何ができないか（git / gh / PAT / hook 早見表）

コンテナ内の `git` と `gh` CLI は認証系統が完全に独立している。`git push` が失敗するのは権限不足ではなく credential helper を意図的に配線していないためであり、`gh` は既定で未認証（`GH_TOKEN` 等の ambient export を持たない）。どちらも `SECRETS_DIR` 配下のトークンファイルを（メイン PAT は明示読みで、MCP／issues 用 PAT は export された値で）使って初めて認証される。

**操作系統別の認証経路と可否**

| 操作 | 認証経路 | コンテナ内での可否 |
|---|---|---|
| git ローカル操作（`commit` / `log` / `diff` / `branch` / `merge` 等） | 認証不要（`commit` のみ `GITCONFIG_FILE` で `user.name`/`user.email` が必要。前述） | 可 |
| git リモート操作（`push` / `pull` / `fetch`） | git credential helper（既定で**未配線**。`SECRETS_DIR/GITHUB_MAIN_PAT` 設定時のみ `GIT_ASKPASS` 経由で配線される） | 既定では **push は不可**。**public リポジトリの fetch/pull は認証不要のため可**（private リポジトリの fetch/pull は不可）。`SECRETS_DIR/GITHUB_MAIN_PAT`（前述）を設定した場合のみ、対象リポジトリへの push（および同トークンでの private リポジトリの fetch/pull）が可能になる |
| `gh` CLI（素） | 認証なし | **既定で未認証・失敗する**（v4〜の正常な既定状態） |
| `gh` CLI（メイン PAT 明示読み） | `GH_TOKEN=$(cat "$GITHUB_MAIN_PAT_FILE") gh ...` | メイン PAT のパーミッション・対象リポジトリの範囲内で可 |
| `gh` CLI（MCP／issues 用 PAT） | `GH_TOKEN="$GITHUB_MCP_PAT" gh ...`（ambient export された値を明示前置） | MCP／issues 用 PAT のパーミッション範囲内で可（通常 Issues のみ） |
| MCP（GitHub 公式サーバー） | `${GITHUB_MCP_PAT}`（`.mcp.json` の Authorization ヘッダ、export 経由） | 同上 |

**メイン PAT / MCP・issues 用 PAT 対応表**

| 項目 | メイン PAT（`SECRETS_DIR` 直下） | MCP／issues 用 PAT（`SECRETS_DIR/export/`） |
|---|---|---|
| 想定用途 | push・PR レビュー・Release 作成等、主対象リポジトリへの広い操作 | issue 連絡・MCP 経由の操作（クロスリポジトリ含む） |
| export | されない（パスのみ `GITHUB_MAIN_PAT_FILE` として export） | される（ファイル名＝環境変数名で値ごと export） |
| 一般的に許可してよいパーミッション | 用途に応じて `Issues`/`Pull requests`/`Contents` を組み合わせる（`Contents: write` を含めると push・PR承認・マージが明示読みで可能になる点を理解した上で） | `Issues: Read and write` のみ |
| 持たせるべきでないパーミッション | — （非 export のため明示読みという一手間が構造的な壁になる） | `Pull requests: write`・`Contents: write`（MCP のツール面に push・マージ等が現れ、スコープを絞らないと実効化するため） |
| 設定手順・スコープ確認 | 「GitHub トークンの配線」節参照 | 同左 |

**ホストの Claude Code 設定（`~/.claude`）の読み書き**

| 対象 | コンテナ内での可否 |
|---|---|
| user scope の設定 11 項目: `hooks/` `skills/` `plugins/` `commands/` `agents/` `workflows/` `rules/` `output-styles/` `settings.json` `CLAUDE.md` `statusline.sh` | 読める・**書けない**（`:ro` 重ねマウント。作成・更新・削除・`/plugin` の install/update・これらへ保存される設定変更はホスト側で行う。ホスト側で更新した内容はコンテナ再起動で反映される）。**plugin について**: plugin のメタデータ（`plugins/known_marketplaces.json`・`installed_plugins.json`）はホストの絶対パスを記録しているため、`claude-container` がホストの `~/.claude/plugins` をホストと同じ絶対パスにも `:ro` で重ねて解決する（`compose.plugins-alias.yml`、[`#98`](https://github.com/jj1xgo/claude-container/issues/98)）。対応範囲は `CLAUDE_CONFIG_DIR`（既定 `~`）がホストの `$HOME` と一致するかその配下にある場合で、それ以外（別基点の指定、ホストの `$HOME` がコンテナ内の `/workspace`・`/data`・`/shared`・`/home/node` の配下にある場合）は起動時に `WARNING` を出し、plugin はコンテナ内で読み込めない（起動は止めない）。例外として、ホストの綴りがコンテナ内の `/home/node/.claude/plugins` と一致する場合は既存の `:ro` マウントで解決するため、別名は付けず `WARNING` も出さない。v8.2.0（`:ro` 化）から本修正までの版では、`entrypoint.sh` の旧機構（JSON の書き換え）が読み取り専用で失敗し、メタデータがコンテナ内で解決できないホストの絶対パスを指す場合（通常のホストはこれに当たる）は `cache-miss` になっていた |
| 認証（`.credentials.json`）・transcript（`projects/`）・auto memory（`projects/<p>/memory/`）・`history.jsonl` 等の状態 | 読み書き可（従来どおり） |
| project scope の設定（`/workspace/.claude/` 配下の settings・skills・agents・commands・rules・CLAUDE.md、`.mcp.json`） | 読み書き可（従来どおり。ホスト側での扱いは「セキュリティモデル」節参照） |

**hook による追加制限**

この保護は `examples/hooks/block-pr-approve.sh` として本リポジトリに同梱されているが、プロダクト本体には配線されていない。適用するには、対象プロジェクトの `.claude/settings.json` に自分で配線する（設定例・回帰テストは `examples/hooks/README.md` を参照）。フォークにもファイル自体はそのまま同梱されるが、配線しない限り動作しない。

| 機構 | ブロックするもの | 通すもの |
|---|---|---|
| PreToolUse hook `examples/hooks/block-pr-approve.sh` | `gh pr review --approve`（短縮形 `-a`、短オプションクラスタ内の `a`、`--approve=true` / `-a=1` 等の値付き指定も含み、偽値・不正値も拒否）／ `gh api …/pulls/<N>/reviews` への `event=APPROVE`（引用符・ヒアドキュメント本文経由を含む） | `--comment`・`--request-changes` 等その他の PR 操作、および gh コマンド全般 |
| `permissions.deny` | （現状未使用 — この保護の機構は上記 hook のみ） | — |

- **役割分担の基準**: `permissions.deny` はコマンドプレフィックス/glob の静的パターンで丸ごと禁止できる場合に向く。本件は「`gh pr review` のうち `--approve` だけ拒否し `--comment` は通す」「生 API の `event=APPROVE` を JSON 本文・ヒアドキュメント内でも検出する」という文脈依存判定が必要で、deny の glob では過剰ブロックか検出漏れのどちらかになるため hook を採用している
- **既知の誤検知**: 残存 false positive（安全方向・許容）＝ 実行コマンドが `gh api` で、ヒアドキュメント本文に `pulls/N/reviews` と `event=APPROVE` の両方を引用したケース、複数行ダブルクォート文字列内の承認文字列、値付き承認フラグの偽値・不正値（値を評価せず拒否。コメント・変更要求では承認フラグ自体を省く）。残存 false negative（脅威モデル外）＝ 引用文字列内の `<<X` でヒアドキュメント除去を誤爆させる意図的難読化。脅威モデルは「Claude 自身のうっかり自律承認の抑止」であり意図的な難読化は対象外
- **参照**: リスクの詳細は「セキュリティモデル」節、hook の実装詳細・配線例・回帰テストは `examples/hooks/README.md`

## セキュリティモデル

信頼できるリポジトリだけを扱う運用での評価と、実装未決定の強化候補は [Sandbox の今後の検討候補](docs/sandbox-considerations.md) に記録している。

Claude は `--dangerously-skip-permissions` で起動するため、ツール使用の確認プロンプトなしに動作する。ガードレールはコンテナ境界 — マウントされたワークスペースと `/data`・`/shared` への読み書きアクセスを持つ。意図したプロジェクトスコープ外の機密データを含むディレクトリはマウントしないこと。`SHARED_MOUNT`（`/shared`）は同じホストパスを設定した全プロジェクトのコンテナが完全な rw アクセスを持つ共有領域のため、相互に信頼できるプロジェクト間でのみ設定すること。

ネットワークは既定で `init-firewall.sh` によるエグレス許可リストで制限される。Claude Code に必要なエンドポイント（Anthropic API・GitHub 等）と `.claude-container.d/allowed-domains.txt` で指定したドメイン以外への外向き通信は遮断されるため、悪意ある pip パッケージやプロンプトインジェクションが認証情報（`~/.claude.json`）やソースコードを任意の外部ホストへ送信することを防ぐ。開放が必要な場合は `.claude-container.d/env` に `CLAUDE_CONTAINER_NO_FIREWALL=1` を書いて無効化できる（自己責任）。

このガードレールが機能するのは、Claude（およびその子プロセス）がこの許可リスト自体を書き換えられないことが前提になる。`Dockerfile.claude` の `ENTRYPOINT`（前述「アーキテクチャ」節参照）でコンテナ起動時に関連 capability（`NET_ADMIN`/`NET_RAW`）を剥奪しており、iptables の実消費者は `sudo` 経由で root になった `init-firewall.sh` のみに限定される。file capabilities 付きバイナリの追加導入や `podman exec` 経由には限界が残る（[詳細](SECURITY-CLAIMS.md#c-1)）。

**制限しても残るリスク**: DNS クエリを使ったトンネリング、許可済みサービス（GitHub 等）自体への送信、CDN の共有 IP 経由の到達は原理上防げない。`/etc/resolv.conf` から IPv4 リゾルバを検出できない場合（通常の Podman 環境では稀）、DNS（53番ポート）は宛先無制限で許可される縮退動作になる（起動時に `WARNING: /etc/resolv.conf に IPv4 リゾルバがないため、DNS を任意のホストへ許可します` が出力される）。許可ドメインの IP は約15秒間隔のバックグラウンド再解決で追従するが（上記アーキテクチャ節参照）、ローテーション直後からリフレッシュが反映されるまでの数十秒間は新規接続が失敗しうる（コンテナ再起動が必要だった以前と比べれば大幅に縮小されるが、ゼロにはできない）。GitHub IP レンジはビルド時スナップショット固定のため、コンテナ再起動では更新されず `-b` でのリビルドが必要。ビルド時（`pip3 install` 等）のネットワークは制限されない。

**`packages.txt`/`requirements.txt` のビルド時インジェクション対策にも残余がある**: 両ファイルは `validate-build-input.sh` による allowlist 検証を経る（前述「利用側プロジェクトの設定」「アーキテクチャ」節）が、PyPI は open publishing のため、`requirements.txt` の名前指定だけで任意パッケージの sdist に含まれる `setup.py` がビルド時 root で実行される経路が原理的に残る（`claude-container#34`）。apt 側は設定済みリポジトリ内のパッケージに限られるため同じ経路は無い。

**claude-in-chrome 連携はファイアウォールでは原理的に遮断できない**（`jj1xgo/claude-container#32`）: `.mcp.json` を介さないネイティブ機能のため MCP 監査ゲートの対象外で、コンテナ内から到達・実行可能である。ホスト側の通知は事前承認ではなく事後通知＋任意キャンセル（fail-open）で、コンテナ内のコードが人間の事前承認なしにホストの実ブラウザを操作しうる——「ガードレールはコンテナ境界」という前提の外側にある残存リスク（[詳細](SECURITY-CLAIMS.md#c-2)）。

**MCP サーバーの承認プロンプトは機能しない**: Claude Code 本来の仕様では project-scoped の `.mcp.json` サーバー利用前に承認プロンプトが表示されるが、`--dangerously-skip-permissions` 下ではこの確認が実行されないことを実機で確認済み（承認記録 `enabledMcpjsonServers` が空のままサーバーが稼働する）。stdio タイプ（コンテナ内でコマンドを実行するサーバー）は、この確認が無いままセッション開始と同時に人間・モデルどちらの判断も挟まず実行され、コンテナ内のトークン類を読めてしまうため、claude-container 側で `entrypoint.sh` による対話確認ゲートを設けている（前述「MCP サーバーの追加」節）。http／sse タイプはこのゲートの対象外だが、接続先はファイアウォールの許可リストが審査する。**残存する経路**: `claude mcp add` によるローカル／ユーザースコープの登録（`~/.claude.json` 側）はこのゲートの対象外で、既に侵害されたセッションによる永続化の手段になりうる。

**`.claude-container.d/env` は信頼できないリポジトリでは攻撃面になる**: `env` で受け付けるキー（前述「環境変数」節の表）には `CLAUDE_CONTAINER_NO_FIREWALL=1` のようなセキュリティ機構の opt-out 変数や、マウント先を決めるキーが含まれるため、そのプロジェクト自身の `.claude-container.d/env` に書かれていれば有効になってしまう。信頼できないリポジトリを起動する前に `.claude-container.d/env` の中身を確認すること。

**`.mcp.json` にだけ追加ゲートがあるのは、入力の信頼度でなく帰結の重大性で線を引いているため**（`claude-container#29`）: リポジトリ同梱の設定（`.claude-container.d/env` と `.mcp.json` の両方）は、いずれも起動前に運用者がレビューする責任範囲にある——同じリポジトリに同梱される以上、どちらか一方だけを「信頼できる」「信頼できない」と区別する根拠は無い。claude-container が追加の対話ゲートを設けるのは、レビューを怠った場合の帰結が「セッション開始と同時の任意コード実行」になる場合に限る（＝ `.mcp.json` の stdio 型）。`env` で受け付けるキーは許可リスト（前述「環境変数」節の表）に限られ、`PATH`・`HOME` 等ホスト側の実行や基点に影響するキーは export されない（[`#44`](https://github.com/jj1xgo/claude-container/issues/44)）。対象プロジェクト直下の `.env` も compose の補間に使わない（[`#60`](https://github.com/jj1xgo/claude-container/issues/60)）。別軸として、境界へ影響するキー（`EXTRA_MOUNT`・`SHARED_MOUNT`・`SECRETS_DIR`・`GITCONFIG_FILE`・`CODEX_DIR` 等）の使用は起動時に一覧して気づけるようにしている（`guard_env_boundary_keys()`）。この可視化は fail-closed ではない——`env` は運用者自身が書く設定という前提は変えていないため。

起動時の可視化を実際に確認したい場合は `.claude-container.d/env` に `CLAUDE_CONTAINER_NO_FIREWALL=1`（または `EXTRA_MOUNT`/`SHARED_MOUNT`/`SHARED_MOUNT_HOME_ALIAS`/`AGENTS_DIR`/`SECRETS_DIR`/`GITCONFIG_FILE`/`CODEX_DIR`/`CLAUDE_CONFIG_DIR`）を書いて起動する。値そのものはログに出さず、キー名のみを一覧する。

**ホストの Claude Code 設定の読み取り専用保護**: ホストの `~/.claude`（`CLAUDE_CONFIG_DIR` 基点）はコンテナへ rw で bind mount される（認証情報・transcript の共有に必要）が、そのうちホスト側で実行・読込される user scope の設定 11 項目（前述「何ができて何ができないか」節の表）は、`compose.yml` が rw マウントの内側に `:ro` の bind mount を重ねることで、**この mount 経由では**コンテナ内から書き換えられない。侵害されたセッションがここへ hook・skill・plugin 等を書くと、ホストの Claude Code がそれを読み込み・実行する（user settings の hooks は file watcher で稼働中セッションにも反映される）ため。マウント先がホストに無いと podman がサブ uid 所有の実体を作って残骸になるので、`claude-container` が起動直前（全ガードと MCP 承認の後）に欠けている項目をユーザー権限で空のまま作り、その旨を `INFO:` で表示する（`--check` は作らず `[WARN]` で報告する）。11 項目のいずれかが symlink または型の違う実体（ディレクトリ予定位置にファイル等）だと起動を中止する。symlink を拒否するのは、`:ro` の子マウントはリンク先に付く一方でリンク自体は rw の親マウント内に残り、コンテナ内で削除して作り直せば書き込み可能な実体に置き換えられる（保護の迂回）ため。**限界**: (1) 保護はこの mount 経由に限る。`/workspace`（作業ディレクトリ）・`EXTRA_MOUNT`・`SHARED_MOUNT` が `~/.claude` を含む、または保護対象そのものを指す場合は別経路から書けるため、起動時に `WARNING` を出す（検出はパスの包含関係のみで、別マウント内部のリンク等は検出しない）。(2) project scope の設定（`/workspace/.claude/` 配下と `.mcp.json`）は対象外で、ホストでそのフォルダを trust 済みならホストの Claude Code がそれらを読み込む。(3) `~/.claude.json`（trust フラグ・user scope の MCP 登録）、auto memory（`projects/<p>/memory/`）、`agent-memory/`、`shell-snapshots/`、`session-env/` は対象外（Claude Code が実行時に書くため）。前 3 者はホスト側セッションへの指示の再注入経路になりうる。(4) 保護された参照元（`settings.json`・`CLAUDE.md` の import・hook や plugin が読む依存ファイル）が `~/.claude` の外や対象外領域を指していれば、その先は保護されない。(5) `.claude-container.d/env` の `HOME`・`PATH` 等でホスト側の実行や基点をずらす経路は、受け付けるキーを許可リストに限定したことで閉じた（`#44`）。許可キーのうち `CLAUDE_CONFIG_DIR` は基点そのものを指定するキーなので、`guard_env_boundary_keys()` の一覧表示の対象にしている。(6) ホスト側で 11 項目のファイルを rename で置換した場合、稼働中のコンテナは旧実体を見続ける（再起動で反映）。(7) plugin の別名マウント（`compose.plugins-alias.yml`、[`#98`](https://github.com/jj1xgo/claude-container/issues/98)）は `plugins/` と同じ source を同じ `:ro` でホストと同じ絶対パスにも重ねるもので、保護対象を増やしも減らしもしない。destination はホストの `$HOME` 配下の綴りに限り、コンテナ内の固定マウント先（`/workspace`・`/data`・`/shared`・`/home/node`）と一致または配下になる場合は付けない（対象プロジェクトや他マウントの内容を隠さないため。判定の正本は `claude-container` の `plugins_alias_target()`）。destination の親ディレクトリ（例 `/home/<host user>`）は podman がコンテナ作成時に root 所有で作るため、コンテナ内の非特権プロセスからは書けない。

`SECRETS_DIR`（前述「GitHub トークンの配線」節）を設定した場合、上記「許可済みサービス自体への送信」というリスクが受動的なものから能動的なものに変わる: プロンプトインジェクションや悪意あるパッケージがコンテナ内からトークンを読み取り（メイン PAT はファイルとして、MCP／issues 用 PAT は export された環境変数として）、そのスコープ内で GitHub 等に書き込める。緩和策は各 fine-grained PAT のスコープ最小化（対象リポジトリ限定・短期限）で、被害を該当リポジトリでの操作に構造的に限定すること。設計上、export されるのは issues 限定等スコープを絞ったトークンのみに留め、広い権限は非 export（明示読みという一手間の壁の向こう）に置くことでこのリスクの既定値を下げている（「GitHub トークンの配線」節の設計原則参照）。`SECRETS_DIR` は汎用機構であるため、この能動的リスクは GitHub トークンに限らず持ち込んだ全シークレットに及ぶ（1コンテナに持ち込むのは実際に使う最小本数に留めること — 前述）。

`CODEX_DIR`（前述「Codex CLI をセカンドオピニオンとして使う」節）を設定した場合、コンテナ内のコードは Codex の認証情報（`auth.json`、ChatGPT アカウントのアクセストークン）を読める。`SECRETS_DIR` と異なり rw マウントのため、コンテナ側から書き込みも可能 — 専用ディレクトリ（実 `~/.codex` でない）を指定する設計により、汚染がホスト側の Codex 実行環境（`config.toml` の `notify` フック等）へ波及する経路を遮断している。Codex は `codex exec` としてセッション中に Claude が判断して実行する通常のコマンドであり、`.mcp.json` には登録しないため、前述の MCP 監査ゲート（TOFU）の対象外である。同ゲートが対象とするのは「セッション開始と同時に人間・モデルどちらの判断も挟まず実行される」経路であり、`codex exec` はそれに当たらない。

`SECRETS_DIR/GITHUB_MAIN_PAT`（前述「git push を使う場合」）に `Contents: write` を付与した場合、能動的リスクは push・PRマージにも及ぶ: プロンプトインジェクションや悪意あるパッケージが、明示読み（`GH_TOKEN=$(cat "$GITHUB_MAIN_PAT_FILE") ...`）を介して対象リポジトリへの意図しないコミット・push・マージを引き起こしうる。非 export であることは「黙ってはできない」という一手間の壁ではあるが、コンテナ内の任意のプロセスがそのファイルパスを読める以上、確実な壁ではない。緩和策は他のトークン同様スコープ最小化（対象リポジトリ限定）に加え、GitHub 側の branch protection（force-push 禁止・レビュー必須化）を組み合わせること。

自リポジトリ向けのメイン PAT に `Pull requests: Read and write` を付与した場合の追加リスク:

- **攻撃対象面の拡大**: 他者PRのタイトル・本文改変、レビュー依頼スパム、妨害目的のクローズが可能になる。Issue操作と同種だが一段重い
- **`Contents: write` を付与しない限りpush・PRマージには至らない**: PRマージ（`PUT …/pulls/{n}/merge`）に必要な権限は `Contents: write` であり、`Pull requests` 権限だけでは実行できない。ただしメイン PAT に `Contents: write` も付与している場合は、この境界は無い（push 節参照）
- **auto-merge 経由の境界迂回に注意**: PRレビュー承認（`gh pr review --approve`）は `Contents: write` なしで実行できる。対象リポジトリで auto-merge が有効な状態だと、コンテナ内トークンによる承認だけで required review 条件が満たされ GitHub 側が自動マージしてしまう可能性がある。auto-merge を無効に保つこと（1枚目の壁）に加え、同梱の PreToolUse hook（`examples/hooks/block-pr-approve.sh`、配線すれば）が承認操作の自律実行を機構的にブロックできる（2枚目の壁 — 適用範囲と限界は「何ができて何ができないか」節参照）。MCP 経由の承認（`mcp__github__pull_request_review_write` 等）はこの hook の検査対象外のため、MCP へは「GitHub トークンの配線」節の `permissions.deny` を別途の壁として使うこと

## Podman 固有の注意

- `userns_mode: keep-id` はホストユーザーの UID/GID をコンテナ内にマップする Podman 固有の機能。Docker に移植する場合は削除する。
- `--in-pod false` は Podman Compose がデフォルトでサービスを Pod にラップする挙動を抑制する。Docker Compose はこのフラグを無視する。

## 変更後の確認

通信の回帰テストはローカル HTTP サーバーと実 curl を使う。
Ctrl-C の確認には util-linux の `script` で疑似端末を用意する。

テストは `lint.sh`、`test-build.sh`（ベクタ表・契約テスト・ランチャーテスト・実イメージのビルドと起動確認）、`examples/hooks/tests/test-block-pr-approve.sh`（同梱 hook の回帰テスト）で行う。スクリプトや Compose / Dockerfile を編集した後は以下で確認する。

GitHub Actions（`.github/workflows/ci.yml`）が、PR と `main` への push のたびに `lint.sh`（Compose 検証を含む）、`./test-build.sh --validator-only`、`./test-build.sh --launcher-only`、`bash examples/hooks/tests/test-block-pr-approve.sh` を `ubuntu-24.04` の runner で実行する。`test-build.sh` は検査の詳細を `.claude/test-results/` のログにしか書かないので、CI はどれかが失敗したときだけそのログを Actions に出す。Compose 検証は runner 同梱の Docker Compose を `PODMAN_COMPOSE_PROVIDER` で指定し、Podman 経由で実行する。Podman と provider が無ければ CI は失敗し、使用した版をログに残す。shellcheck はホストの開発環境と同じ版を SHA256 固定で取得する。実コンテナ検証は独立した手動・定期 workflow（`.github/workflows/runtime.yml`）で行う。`test-build.sh --build-only` と `--config-ro-only` を再利用し、起動後の権限・IPv4 の許可／禁止通信も確認する。PR の必須チェックは増やさない。実行方法・runner の前提・`not run` の扱いは [実コンテナの手動・定期検証](docs/runtime-ci.md) を参照。追加パッケージ・不正入力のビルド検査を含む `./test-build.sh` の全体実行は引き続きホストで行う。fork からの PR は GitHub の設定により初回の実行が承認待ちになることがあり、その間は赤でも緑でもない。

```bash
./lint.sh
```

`lint.sh` は、リポジトリ内の bash スクリプト（gitignore 対象を除く追跡済み・未追跡ファイルから shebang で自動判定するため、スクリプトを追加・削除しても対象リストの更新は不要）への `bash -n` と `shellcheck`、および `podman compose -f compose.yml config` をまとめて実行する。shellcheck 未インストール時はエラーで失敗する（`sudo apt-get install shellcheck` で導入）。podman が無い環境（コンテナ内での開発時）では Compose 検証のみ警告付きでスキップされる。`LINT_SKIP_COMPOSE=1` を与えると、podman の有無に関わらず Compose 検証だけを警告付きでスキップする（Compose を実行できない環境用。CI では指定しない）。

`compose.yml` の `:ro` 重ねマウント、または `claude-container` の `prepare_claude_config_ro()` を編集した場合は、ビルド済みのテストイメージ `localhost/claude-test`（`./test-build.sh` の全実行で作られる）がある状態で `./test-build.sh --config-ro-only` を実行する。実物の `compose.yml` とイメージで 11 項目への書き込みが拒否されること、実物のランチャーが placeholder 作成・型検査・`--check` の無書き込み・compose への `CLAUDE_CONFIG_DIR` 受け渡しを正しく行うことを、それぞれ別のテストで確認する（両者を通した対話起動は手動で行う）。

`claude-container` のガード関数（`guard_*`・`prepare_claude_config_ro()`）を編集した場合は `./test-build.sh --launcher-only` を実行する。podman をダミーに置き換えた隔離環境（一時 `HOME`・空の環境変数）で実物のランチャーを起動し、各ガードの通常起動と `--check` の挙動、compose へ渡る環境変数を検証する。実 podman が不要なので、コンテナ内の開発セッションや CI からも回せる。通常の `./test-build.sh` にも含まれる。

IPv6 の変更時は `./test-build.sh --launcher-only` に含む Python テストと設定テストを実行する。`lint.sh` は通常と IPv6 override の両方の Compose 設定を検証する。実 IPv6 の確認は pasta を使うコンテナで別途行う。

plugin の別名マウント（`compose.plugins-alias.yml`・`plugins_alias_target()`・`guard_plugins_alias()`）の変更時も `./test-build.sh --launcher-only` を実行する（判定関数の単体検査、build・run 各呼び出しへの配線、`--check` の不変を含む）。`lint.sh` は override 単独と IPv6 override との 3 ファイル同時の Compose 設定も検証する。plugin が実際に読み込まれるかは `-b` で起動したコンテナ内の `claude plugin list` で確認する（`entrypoint.sh` にはこの境界のマーカーコメントがあり、`tests/test_ipv6_entrypoint.py` が抽出境界として使う — 文言を変えたらテスト側も同時に変える）。

`SHARED_MOUNT` の別名マウントと `AGENTS_DIR`（`compose.shared-home.yml`・`compose.shared-host.yml`・`compose.agents.yml`・`guard_shared_home_alias()`・`guard_agents_dir()`）の変更時も `./test-build.sh --launcher-only` を実行する（opt-in の配線、不正値の拒否、`--check` の不変、symlink の実体解決を含む）。このランチャーテストの仮 HOME は `mktemp` 配下に作るため、`TMPDIR` が `/var/tmp` や `/run/user/<uid>` の配下だと予約領域の拒否条件に当たり、正常系も失敗する。該当する環境では `TMPDIR=/tmp ./test-build.sh --launcher-only` として実行する（全体テストも `TMPDIR=/tmp ./test-build.sh`）。`lint.sh` は override 単独と 6 ファイル同時の Compose 設定、`${VAR:?}` の fail-closed を検証する。実際に別名が読めて別名経由で書けないこと、`/shared` が rw のままであることは `-b` で起動したコンテナ内で確認する（前述「ホストの指示ファイルとスキルをコンテナ内で解決する」節）。

`init-firewall.sh` の `resolve_allowed_ports()`・`build_domain_list()`・`refresh_domains()`・`add_or_touch_domain_ip()`・`prune_stale_domain_rules()` を編集した場合も `./test-build.sh --launcher-only` を実行する。ポート検証、許可ドメイン入力検証（`tests/test-allowed-domains.sh`）と DNS 応答の回帰テスト（`tests/test-refresh-domains.sh`）、ルールの更新順序・世代非更新・期限切れ削除の回帰テスト（`tests/test-domain-rule-lifecycle.sh`）を含む。各テストは `bash tests/<ファイル名>.sh` で単独実行できる。実際の iptables と接続の確認は別途コンテナで行う。

`Dockerfile.claude`（`ENTRYPOINT` の `setpriv` ラップ）を編集した場合は `-b` でのリビルドと実機起動が必須（前述「セキュリティモデル」節参照）。コンテナ内セッションから `sudo` 無しの `iptables` 操作ができないことが正しい状態であり、ファイアウォールルール自体の確認は `podman exec --user root <container> iptables -S`（ホスト側から）で行う——セッション内からの `iptables -S` 単体実行は権限剥奪後には失敗するようになる。

## 表記

この repo の文書・スクリプトのメッセージとコメント・tag メッセージ・Release 本文・Issue と PR は**日本語のみ**で書く。v8.2.1 までは README と tag が日英併記だったが、v8.2.1 を最後に英語版を廃止した（既存の tag と Release は書き換えない）。例外として英語のまま残すのは、`ERROR:` / `WARNING:` / `INFO:` / `[OK]` / `[WARN]` / `[FAIL]` の接頭辞（テストと `--check` の集計が照合する機械可読トークン）、`[y/N]`、環境変数名・関数名・コマンド名・URL、`LICENSE` の法文、git や gh が出す文字列と照合する部分。日本語の文中の技術用語（base image、stdio、hash、fail-closed 等）は英語のまま書いてよく、「行にひらがなかカタカナが含まれる」ことを日本語化済みの判定に使う。

## バージョニング

[Semantic Versioning](https://semver.org/lang/ja/) に従い、リリースは annotated git タグ（`vX.Y.Z`）で管理し、タグごとに、タグメッセージを本文にした GitHub Release を作成する（CHANGELOG ファイルは作らない）。`--notes-from-tag` は `-R` と併用できない（gh 2.100.0 で実測）ので、本文はファイル経由で渡す:

```bash
git tag -l --format='%(contents)' vX.Y.Z > /tmp/notes.txt
gh release create vX.Y.Z -R jj1xgo/claude-container --verify-tag --title vX.Y.Z --notes-file /tmp/notes.txt
```

番号は利用者から見えるインターフェース（CLI 引数・`.claude-container.d/` の設定形式・デフォルト挙動）を基準に判定する:

- **MAJOR** — 後方互換性が壊れる変更（デフォルト挙動の変更、設定形式の削除・非互換化など、利用者が対応しないと従来どおり動かないもの）
- **MINOR** — 後方互換な機能追加（既存の使い方はそのまま動く）
- **PATCH** — 後方互換なバグ修正のみ

バージョン履歴は GitHub の [Releases ページ](https://github.com/jj1xgo/claude-container/releases)で一覧・購読できる（`git tag -n1` でも確認可能）。

## 参考

- [Running Claude Code CLI in a Container (Endpoint Dev Blog)](https://www.endpointdev.com/blog/2026/03/claude-code-cli-in-container/) — フォーク元作者 Seth Jensen によるコンテナ化の解説記事

## ライセンス

GPL-3.0。フォーク元（sethjensen1/claude-container）は MIT ライセンス。詳細は [LICENSE](LICENSE) を参照。
