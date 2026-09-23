# c3c — Claude Code & Codex Container

[sethjensen1/claude-container](https://github.com/sethjensen1/claude-container) をフォークした Podman 上の Claude Code コンテナ実行環境。

Podman + Compose を使い、ホストの Claude 認証情報を共有しながら任意のディレクトリを `/workspace` にマウントして Claude Code を起動する。

apt/pip パッケージは `.c3c/`（後述。旧名 `.claude-container.d/` も移行期間中は読める）でプロジェクトごとに指定でき、本リポジトリ自体にはプロジェクト固有のパッケージを持たせない。

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
- [Codex CLI を対話で使う](#codex-cli-を対話で使う)
- [c3c 入口（CLI の選択と記憶）](#c3c-入口cli-の選択と記憶)
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
- 残存イメージの診断・清掃にホストの Python 3.9 以上とローカル Podman（`rmi --no-prune` / `ps --external` 対応版）
- `c3c` の CLI 選択の記憶（前回の CLI を同じリポジトリで既定にする機能）に同じホストの Python 3。無くても `c3c claude` / `c3c codex` の明示指定は動く（後述「c3c 入口」節）
  - 実機検証は Podman 5.8.6。非対応オプションや未知の JSON 形式は清掃を失敗として報告し、強制削除へ切り替えない。
- ホストに `~/.claude.json`（Claude 認証情報）が存在すること

## 使い方

公開リポジトリは [jj1xgo/c3c](https://github.com/jj1xgo/c3c)（旧名 `jj1xgo/claude-container`）。origin が旧 `jj1xgo/claude-container` を指す既存 clone では、そのリポジトリ内で origin を更新する。

```bash
# HTTPS の場合
git remote set-url origin https://github.com/jj1xgo/c3c.git
# SSH の場合は上のコマンドに代えて次を使う
# git remote set-url origin git@github.com:jj1xgo/c3c.git
git fetch origin
```

ローカルの checkout ディレクトリ名や、checkout 内の `c3c` を指す既存の起動用 symlink はそのまま使える（削除済みの旧実行ファイル `claude-container` を指す symlink は後述「旧コマンドからの移行」）。旧 URL の転送は GitHub が提供するが、旧リポジトリ名を再利用すると失われる（[GitHub の改名仕様](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository)）。

```bash
# 任意のディレクトリで Claude Code を起動
./c3c claude /path/to/project

# イメージを強制リビルドして起動
./c3c claude -b /path/to/project

# 同じ外側境界の中で Codex CLI を起動する（サブコマンドで CLI を明示）
./c3c codex /path/to/project
# Codex を read-only sandbox で起動する（諮問・レビュー用。Codex 専用）
./c3c codex --read-only /path/to/project

# そのプロジェクトのイメージ・ネットワーク・ビルドコンテキストを削除して終了
./c3c --clean /path/to/project

# 全プロジェクト分のイメージ・ネットワーク・ビルドコンテキストを削除して終了
./c3c --clean

# 起動せず設定を診断（引数なしなら起動台帳の全プロジェクトを一括診断）
./c3c --check
./c3c --check /path/to/project

# 削除済みパスに対応する、確認済みのイメージだけを清掃する（台帳は保持）
./c3c --check --clean-missing
./c3c --check --clean-missing /path/to/deleted-project
```

入口は通常ファイルの `c3c` だけ。サブコマンドで CLI を選ぶ・無指定なら前回の CLI を使う・ディレクトリ省略で現在のディレクトリを使う（詳細は後述「[c3c 入口（CLI の選択と記憶）](#c3c-入口cli-の選択と記憶)」）。旧入口 `claude-container` は削除済み。旧実行ファイルを指していた symlink・wrapper は `c3c` へ向け直す必要があり、向け直した後は旧名で呼んでも `c3c` と同じ解釈になる（後述「[旧コマンドからの移行](#旧コマンドからの移行)」）。

```bash
# インストール例（PATH 上に symlink を置く。相対・絶対・多段のどれでもよい）
ln -s /path/to/checkout/c3c ~/.local/bin/c3c

# CLI を明示して起動（ディレクトリ省略時は現在のディレクトリ）
c3c claude /path/to/project
c3c codex
# 無指定: 同じリポジトリで前回正常終了した CLI を使う。初回は端末で 1（Claude）/ 2（Codex）を尋ねる
c3c /path/to/project
# Codex を read-only sandbox で（最終的に選ばれた CLI が Claude なら終了コード 2）
c3c codex --read-only
# 診断・清掃は CLI を尋ねず、前回の選択も読まない・変えない
c3c --check
c3c codex --check /path/to/project
c3c --clean /path/to/project
```

スクリプトはシンボリックリンク経由でも動作する（`c3c` を指していれば旧名 `claude-container` を含むどの呼出名でも、実ファイルまで symlink を辿ってから自身のディレクトリを解決する。絶対・相対・多段リンク、PATH 経由、`bash ./c3c` のいずれも同じ基点になり、解決できない場合は起動前にエラーで止まる）。異なるターゲットプロジェクトを交互に起動・リビルドしても互いのイメージ・ビルドコンテキストを上書きしない（後述「アーキテクチャ」参照）。同時に別々のプロジェクトを起動することもできる。

通常起動には実在してアクセスできるディレクトリが必要で、不正なパスは `ERROR:` で案内する。`--clean <ディレクトリ>` は、削除済みでも起動台帳（`~/.local/state/claude-container/projects`）に同じ絶対パスが残っていれば実行できる。相対パス・`.`・`..`・末尾の `/` は正規化し、シンボリックリンクの綴りは起動時と同じものを使う（リンク先の実体パスとは別プロジェクト扱い）。先頭が `//` の綴りで起動したプロジェクトは対象外（bash は先頭の `//` を保持し `realpath` は `/` に畳むため、削除後の照合が一致せずエラーで停止する）。台帳にない削除済みパスや、改行を含む削除済みパスからは清掃対象を推測せず、エラーで停止する。現在のディレクトリを特定できない場合（cwd が削除済みで環境の `PWD` も無いか空）も、相対パスからは対象を推測せず、絶対パスの指定を求めてエラーで停止する。cwd が削除済みのまま `.`・`..` を指定した場合も同様で、bash は削除済み cwd からの `cd .` を成功させ `pwd -L` が `.` をそのまま返すため、通常起動・`--clean`・`--check` のいずれも `.` の幽霊名で清掃・台帳記録・診断を始めず、絶対パスの指定を求めてエラーで停止する。対象のイメージ・ネットワーク・ビルドコンテキスト・MCP 承認記録・台帳エントリを清掃するほか、従来どおり最後に dangling イメージ全体を整理する。

`CDPATH` を使って相対パスから起動したプロジェクトを削除した場合は、起動台帳に記録された絶対パスを `--clean` に指定する。削除済みパスの復元では `CDPATH` を探索しない。

### 旧コマンドからの移行

旧入口 `claude-container` の実行ファイルは削除済み（旧入口を残した最後のメジャー版は v11 系。廃止予告と移行診断は v11.1.0 で提供した）。`c3c` が唯一の入口である。

- 削除済みの `<checkout>/claude-container` を指していた symlink・wrapper・alias は、リンク先が無くなるため起動できない（シェルの「No such file or directory」で止まり、launcher の案内は出ない）。`<checkout>/c3c` へ向け直す。
- `c3c` を指す旧名の symlink・alias から呼んだ場合は起動できるが、引数解釈は `c3c` と同じになる（無指定なら前回の CLI、旧 parser は復活しない）。

PATH 上の入口を checkout の `c3c` に向け、alias・wrapper・Makefile・CI・cron 等の呼び出しを次の表で更新する。

| 旧呼び出し | 移行後 |
| --- | --- |
| `claude-container <dir>` | `c3c claude <dir>` |
| `claude-container -b <dir>` | `c3c claude -b <dir>` |
| `claude-container --agent codex <dir>` | `c3c codex <dir>` |
| `claude-container --agent codex --read-only <dir>` | `c3c codex --read-only <dir>` |
| `claude-container --check [<dir>...]` | `c3c --check [<dir>...]` |
| `claude-container --agent codex --check <dir>` | `c3c codex --check <dir>` |
| `claude-container --clean [<dir>]` | `c3c --clean [<dir>]` |
| `claude-container --check --clean-missing` | `c3c --check --clean-missing` |

従来の Claude 固定の呼び出しは **`c3c claude` と明示する**。`c3c` 無指定は前回の CLI を使う（記憶が無く端末も無ければ終了コード 2）ため、単なるコマンド名の置換では同じ動作にならない。`claude` / `codex` という相対ディレクトリは `./claude` / `./codex`、先頭が `-` のパスは `--` の後に指定する。通常起動のディレクトリは最大1件で、未知オプションは拒否する。

`--check` は入口移行の案内（旧入口は削除済み、外部の呼び出しは `c3c claude` / `c3c codex` へ）を表示する。外部のスクリプト・alias・PATH を自動走査する機能ではなく、案内が出ないことは利用側すべての移行完了を意味しない。

切替後は `c3c --check` と各 CLI の起動を確認する。問題があれば、旧入口を残した v11 系（v11.1.0 以降）の checkout に戻す。`c3c claude` / `c3c codex` は互換版でも利用できる。設定・認証・承認記録・CLI 選択の記憶の削除や再作成は不要。旧設定 `.claude-container.d/` の互換読込や内部の保存先（`CLAUDE_CONTAINER_*` の env キー、`~/.local/state/claude-container/`、イメージ名）は今回のコマンド削除とは別で、引き続き維持する。

## 起動前チェック（`--check`）

複数のファミリープロジェクトが本リポジトリを直接参照して稼働している運用（内部運用issue参照）では、破壊的変更（v3.0.0 の旧設定形式削除、v4.0.0 のトークン配線変更等）の後、各プロジェクトの設定を更新しないと起動が fail-closed ガードで停止する。`--check` は起動せずにこれを事前診断し、リビルド・起動前に必要な移行作業を一括提示する。

```bash
# 起動台帳（後述）の全プロジェクトを一括診断
./c3c --check

# 個別のディレクトリを診断（複数指定可）
./c3c --check /path/to/project-a /path/to/project-b
```

通常の `--check` は台帳が空でも残存イメージを調べ、台帳外のイメージ、欠落パスの候補、由来不明の候補を報告する。明示したパスがある場合は、そのパスに対応すると確認できるイメージだけを報告する。Python または Podman がない場合はこの追加診断をスキップする。利用可能でも一覧取得・JSON 解析・台帳検査などに失敗した場合は、プロジェクトの設定診断が成功していても終了コードは非 0 になる。通常診断ではイメージを削除しない。

### 欠落パスのイメージ清掃（`--check --clean-missing`）

明示した場合だけ、元の論理絶対パスが欠落し、由来と名前が一致し、稼働中・停止中・ビルド用コンテナから参照されていないイメージを削除する。引数なしなら台帳とイメージの由来ラベルを調べるため、台帳を移動先へ更新した後も、ラベルが残る旧イメージを見つけられる。権限拒否、通常ファイルへの置換、壊れた symlink、検査エラーは欠落として扱わない。旧 symlink 自体を削除した場合は、元の綴りを指定する。改行を含むパスは、`.` / `..` 等の相対指定を解決した後も清掃対象にしない。

現在の名前が `localhost/<project>_claude-auth-workspace:latest` だけのイメージが対象。別名・別タグ付き、名前なし、由来不明・不整合のものは保持する。旧イメージは、台帳の完全一致パスから現在の名前を一意に確認できる場合に限り対象となる。名前なし候補は、由来ラベルから欠落パスを確認できたものだけを個別表示し、それ以外は件数を表示する。詳細は `podman images --all --no-trunc` と `podman image inspect <id>` で確認する。

削除前に対象を表示し、対象ごとに名前・ラベル・パス・参照を再検査する。強制削除や全体 prune は使わず、`rmi --no-prune` で親イメージも保持する。中間イメージ・キャッシュが残るため、ディスク使用量の回収が小さい場合がある。結果には削除成功・対象なし・保留理由・失敗を分けて表示する。**台帳、ネットワーク、MCP 承認記録、ビルドコンテキストは変更しない。** 台帳を保持するので、後から従来の `--clean <path>` も使える（この旧コマンドは全体の dangling prune を伴う）。清掃後も通常の `--check` は欠落台帳パスを FAIL として報告する。清掃モードで対象イメージが既にない場合は正常終了する。由来ラベルから見つかった台帳外の実在ディレクトリも、清掃モードでは通常のプロジェクト診断に回す。

新しいビルドには `claude-container.project-metadata` / `project-path` / `project-name` ラベルを記録する。**ホストの絶対パスはイメージを共有・export した場合にも含まれる。** 既存イメージへの後付けはせず、次回 `-b` または暗黙ビルドから付く。Dockerfile の変更による既存のドリフト診断は、従来どおり再ビルドを案内する。改行や先頭 `//` を含むパスは清掃用の由来情報を付けない。

清掃はこのホストのローカル Podman を対象とし、`--remote=false` で接続先の切り替えを防ぐ。未マウントの媒体・切断中の共有上のプロジェクトも欠落と判定されうるため、媒体を接続した状態で実行する。検査と削除は全体として原子的ではないので、同時にビルド・タグ変更・起動・移動を行わない。読み取りの Podman 検査は30秒を上限とし、タイムアウトも失敗として報告する。削除処理には上限を設けず完了を待つ（ストレージ更新中の強制終了を避けるため）。

| 終了コード | 清掃モードの結果 |
| --- | --- |
| `0` | 対象の清掃成功または対象なし。名前なし・由来不明の候補報告だけでは失敗にしない |
| `1` | 診断・削除・消失確認の失敗、必要な依存の不在、対象の参照・別名・由来矛盾・パス検査不能 |
| `2` | `--clean-missing` 単独、`--clean` と `--check` / `--clean-missing` の併用 |

### 通常診断の契約

- **起動台帳**: 通常起動（`--clean`/`--check` を除く）のたびに、対象ディレクトリのホスト絶対パスが `~/.local/state/claude-container/projects` へ自動記録される（手動メンテ不要）。`--check` を引数なしで実行すると、この台帳に記録された全プロジェクトを一括診断する。`--clean <directory>` はそのプロジェクトを台帳からも削除し、`--clean`（引数なし）は台帳自体を削除する。シンボリックリンク経由と実体パスで起動すると別エントリとして記録される点に注意（`compute_project_name()` のプロジェクト識別基準と同じ）。
- **検査項目**: 設定ディレクトリの選択（`.c3c/` と旧 `.claude-container.d/` の有無・型・二重配置。前述「利用側プロジェクトの設定」節）・legacy トークン変数（`GH_TOKEN_FILE` 等）・`SHARED_MOUNT`/`SHARED_MOUNT_HOME_ALIAS`/`AGENTS_DIR`/`GITCONFIG_FILE`/`SECRETS_DIR`/`CODEX_DIR` の存在とレイアウト（`noexport/` 残存等）・パーミッション・`packages.txt`/`requirements.txt`/`allowed-domains.txt` の有無・イメージの既ビルド有無（`podman` 利用可能な場合のみ）・MCP 監査ゲートの承認状態・`packages.txt`/`requirements.txt` の内容診断。**起動時ガードと内容診断は別モードで動く**: 上記の有無チェック等は通常起動時の fail-closed ガードと同一の関数を共有し診断結果と実際の起動挙動が乖離しないが、内容診断（`packages.txt`/`requirements.txt` の allowlist 検証）は `--check` 専用の助言診断で、通常起動時の強制点（`Dockerfile.claude` の `RUN`）とは別に呼ばれる。ただし両者は同じ `validate-build-input.sh` を呼ぶため、判定ロジック自体が乖離することはない。
- **非対話・対象リポジトリは不変**: `--check` は TTY 確認を一切行わない（MCP stdio 型サーバーが未承認の場合は「初回起動時に確認プロンプトが出ます」と報告するのみ）。台帳に記録があるが実体が見つからないプロジェクトも FAIL として報告するだけで、台帳を黙って書き換えない。**保証の範囲は「対象リポジトリと `.build-context/` を変更しない」こと**（内容診断は `mktemp` 経由で `/tmp` 配下に作業ファイルを必ず作るため、無限定の「書き込みゼロ」ではない）。
- **終了コード**: 診断対象のいずれかが FAIL の場合は非0、それ以外は0で終了する。`-b` は `--check` と併用しても無視される。

## 環境変数

**利用側プロジェクト**のルートに `.c3c/env`（旧名 `.claude-container.d/env` も移行期間中は同じ扱い。両方は置けない。後述「利用側プロジェクトの設定」節）を置くと起動前に自動で読み込まれる。読み込まれるのは `KEY=VALUE` 形式の行のうち **下表のキーだけ**で、クォートやシェル展開は解釈されない（ホスト上でのシェル構文の即時解釈を避けるため、意図的に `source` していない）。下表にないキーは export されず `WARNING` を出して無視する（[`#44`](https://github.com/jj1xgo/claude-container/issues/44)。`PATH`・`HOME`・`LD_PRELOAD` 等、ホスト側で動くランチャーや podman・git・gh の挙動を変えうるキーをリポジトリ側から書けないようにするため）。また、対象プロジェクト直下の `.env` は compose の変数補間に使わない（`podman compose` を `--env-file /dev/null` で呼ぶ。[`#60`](https://github.com/jj1xgo/claude-container/issues/60)）。リポジトリ同梱のファイルから設定できる入口は `.c3c/env` の 1 つだけである（シェル環境から渡した変数は従来どおり有効なので、以前 `env` に書いて効いていた `PATH`・`PODMAN_COMPOSE_PROVIDER`・`CLAUDE_CODE_VERSION` 等はシェル環境へ移すこと。例: `CLAUDE_CODE_VERSION=1.2.3 ./c3c claude <dir>`）。これはビルド時に焼き込まれる設定ではなく起動のたび毎回読み込まれるランタイム設定なので、変更してもリビルド（`-b`）は不要。

| 変数 | デフォルト | 説明 |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | `~` | `.claude.json` と `.claude/` が置かれているディレクトリ。後述「ホストの Claude Code 設定の読み取り専用保護」の基点でもある。絶対パスか `~/` 始まりで指定する（相対パスは起動を中止する） |
| `EXTRA_MOUNT` | `/dev/null` | コンテナ内 `/data` に追加でマウントするホスト側パス |
| `SHARED_MOUNT` | `/dev/null` | コンテナ内 `/shared` に追加でマウントするホスト側パス。複数プロジェクトからの共有ディレクトリ参照向け（`EXTRA_MOUNT` と併用可）。設定済みでパスが無い場合は起動を中止 |
| `SHARED_MOUNT_HOME_ALIAS` | `0` | `1` で `SHARED_MOUNT` のディレクトリを、`/shared`（rw）に加えてコンテナ内の `~`（`/home/node`）配下の同じ相対位置と、ホストと同じ絶対パスにも `:ro` で重ねる（後述「ホストの指示ファイルとスキルをコンテナ内で解決する」節）。`SHARED_MOUNT` がホストの `$HOME` 配下で、`$HOME` 直下の項目名が `.` で始まらないことが条件。ホスト絶対パス別名がコンテナの予約領域（下記参照）と重なる場合も拒否する。条件を満たさない値と `0`/`1` 以外の値は起動と `--check` で拒否 |
| `AGENTS_DIR` | (unset) | Codex 等のエージェント共通のスキル置き場（通常 `~/.agents`）をコンテナ内 `~/.agents` として `:ro` マウントするホスト側パス。絶対パスか `~/` 始まりで指定する。`~/.claude/agents/`（Claude Code の subagent 定義、後述の `:ro` 保護 12 項目の一つ）とは別物 |
| `TZ` | ホストから自動検出 | コンテナ内のタイムゾーン |
| `CLAUDE_CONTAINER_IPV6` | `0` | `1` で IPv4/IPv6 を併用し両方に許可リストを適用する。未指定・空・0は既存IPv4モード、その他は起動と `--check` で拒否。初回は対応イメージの `-b` が必要（後述） |
| `CLAUDE_CONTAINER_NO_FIREWALL` | (unset) | `1` でエグレス制限（後述）を無効化 |
| `GITCONFIG_FILE` | (unset) | コンテナ内 `~/.gitconfig` として read-only マウントするホスト側 git 設定ファイルのパス（後述） |
| `SECRETS_DIR` | (unset) | GitHub トークン等のシークレットをコンテナへ持ち込む唯一の機構のホスト側パス（後述「GitHub トークンの配線」節） |
| `CODEX_DIR` | (unset) | Codex CLI の認証情報ディレクトリ（`auth.json` 等）をコンテナへ rw マウントするホスト側パス。専用ディレクトリを推奨（後述「Codex CLI をセカンドオピニオンとして使う」節）。絶対パスか `~/` 始まりで指定する（相対パスは起動を中止する）。実ホストの `~/.codex` と同じ実体を指す指定（表記ゆれ・シンボリックリンクを含む）は起動を中止する |

`TZ` は起動スクリプトがホストの `/etc/timezone`（なければ `/etc/localtime` シンボリックリンク）から自動検出する。`.c3c/env` またはシェル環境で明示した場合はそちらが優先される。

claude-container 自身を対象プロジェクトとして自己ホスト起動する場合（このリポジトリを直接 `./c3c claude` の引数に渡す場合）は、`examples/c3c/env.example` をコピーして `.claude-container.d/env` を作成する（このリポジトリ自身の設定ディレクトリは移行期間中 `.claude-container.d/` のままで、自己ホスト起動では移行推奨の WARNING が出る。ルートに `.c3c/` を置くと自身の設定と二重配置になるため、サンプルは `examples/` 配下にある）。`SECRETS_DIR` 等ホスト固有のパスを含みうるため `env` は新旧どちらの名前でも gitignore 対象で、リポジトリには example のみをコミットする。同様に、GitHub 公式 MCP サーバー（後述「GitHub トークンの配線」節のレシピ参照）を自己ホスト環境でも使いたい場合は、`.mcp.json.example` をコピーして `.mcp.json` を作成する（`.mcp.json` はメンテナ自身のセッション用実設定のため gitignore 対象）。

## IPv6 を任意で有効にする

既定は IPv4 のみ。IPv6 も使うプロジェクトは `.c3c/env` に次を追加する:

```text
CLAUDE_CONTAINER_IPV6=1
```

初回は `./c3c claude -b /path/to/project` で新しい境界アセットを含むイメージを作る。対応ラベルのない旧イメージでの有効化は、起動と `--check` で再ビルドを案内して停止する。その後の0/1の切り替えはランタイム設定なので、コンテナを終了して起動し直せば反映される。IPv4/IPv6 で `allowed-domains.txt` と `allowed-ports.txt` を共用し、IPv6 でも未許可の宛先・ポートを遮断する。IPv6-only ホストは初期対応の対象外で、IPv4 も使用できることが前提。

有効時は launcher が固定の `compose.ipv6.yml` を追加し、単独 pasta と仮想 IPv6 ゲートウェイ `fe80::1` を使う。Podman/pasta、ホストの IPv6 外向き通信と、ip6tables の hop-limit / REJECT 機能を使えるカーネルが必要。これらが使えない場合は初期化を失敗として停止する。今回確認した環境は rootless Podman 5.8.6 / podman-compose 1.6.0。ホストに IPv6 があっても rootless bridge の外側へ経路が渡らない場合があるため、コンテナ単位に閉じた pasta を使う。ホスト・ルーター・WARP の設定は自動変更しない。起動時には経路、IPv6 有効状態、ip6tables、`api.anthropic.com` の IPv6 HTTPS 接続と禁止先の遮断を検査し、失敗したら起動を止める。`--check` は設定値だけを検査し、ネットワーク作成や実疎通は行わない。

既定の IPv4 モードは既存 bridge のまま。有効時は共有 bridge を再利用せず、pasta はコンテナ終了時に片付く。過去の bridge は必要なら既存の `--clean <project>` で整理する。pasta で検出する IPv4 ゲートウェイは物理側ルーターの場合があり、bridge のゲートウェイと同じホストサービスの別名ではない。Podman は既定で `--no-map-gw` を指定し、ゲートウェイからホスト loopback への写像を無効にする（[Podman のネットワーク仕様](https://docs.podman.io/en/v5.8.0/markdown/podman-run.1.html#network-mode-net)）。IPv6 ゲートウェイへの TCP/UDP 全許可は追加しない。ホスト側サービスへの接続があるプロジェクトは切り替え時に確認する。

IPv6 の許可対象は `2000::/3` の global unicast と `fc00::/7` の ULA。未指定・loopback・IPv4-mapped・multicast・link-local などの AAAA 応答は警告して除外する。link-local 宛てサービスや変換用プレフィックスの明示許可は初期対応外。DNS リゾルバへの53番と、近隣探索・Path MTU Discovery 等に必要な ICMPv6 は別ルールで許可する。AAAA がない正常応答と NXDOMAIN はスキップし、一時的な解決失敗は起動時にエラー、定期更新時に警告とする。IPv6 のルールも約15秒ごとに更新し、約3分観測されないものを削除する。

アドレス表記の正規化と IPv6 ルール管理には、イメージに固定導入する `python3` と root 所有の `ipv6-firewall.py` を使う。追加の Python パッケージは不要。`CLAUDE_CONTAINER_NO_FIREWALL=1` を明示した場合は、既存の無効化設定として IPv4/IPv6 両方のファイアウォール初期化を省略する。

## ホストの指示ファイルとスキルをコンテナ内で解決する

ホストの `~/.claude/CLAUDE.md` はコンテナへ `:ro` で共有される（後述「ホストの Claude Code 設定の読み取り専用保護」）。その中で `@~/obsidian-vault/knowledge/索引.md` のように `~` 起点で別のディレクトリを参照していると、コンテナ内の `~` は `/home/node` なので参照先が無く、指示が展開されない。同様に Codex 等が共通で読む `~/.agents/skills/` もコンテナ内には無い。グローバル指示をホストとコンテナで二重管理せず、参照先をコンテナ側で解決するための opt-in が 2 つある（[`#99`](https://github.com/jj1xgo/claude-container/issues/99)）。

```bash
# .c3c/env
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

利用側プロジェクトの claude-container 向け設定は、起動 checkout 直下の `.c3c/` ディレクトリに一本化されている（c3c 第2b-1段階で旧名 `.claude-container.d/` から改名。旧名も移行期間中は読める。後述「旧 `.claude-container.d/` からの移行」）。中身は「起動のたび読み込まれるランタイム設定」と「ビルド時にイメージへ焼き込まれる設定」の2種類に分かれる。

```
.c3c/env                  # ランタイム設定（KEY=VALUE、上記「環境変数」参照）。-b 不要、gitignore 対象
.c3c/packages.txt         # apt パッケージ（1行1パッケージ、素のパッケージ名のみの allowlist 検証あり。行頭 # はコメント）。-b 必須、コミット対象
.c3c/requirements.txt     # pip パッケージ（名前＋extras＋バージョン指定子のみの allowlist 検証あり。URL・パス・オプション行・環境マーカー・行内空白は拒否しビルド停止。行内 # 以降はコメントとして剥がされる）。-b 必須、コミット対象
.c3c/allowed-domains.txt  # エグレス制限に追加する許可ドメイン（1行1ホスト名、行頭 # はコメント。起動・更新時の入力検証あり）。-b 必須、コミット対象
.c3c/node-version.txt     # 導入する Node.js のバージョン（例: 22.14.0、1行のみ。置かなければ同梱 default の 24.18.0、空ファイルは導入しない opt-out）。-b 必須、コミット対象
.c3c/codex-version.txt    # 導入する Codex CLI のバージョン（例: 0.156.0、または latest。1行のみ。置かなければ同梱 default の 0.156.0、空ファイルは導入しない opt-out）。-b 必須、コミット対象
.c3c/allowed-ports.txt    # エグレス許可を限定するTCPポート（1行1ポートまたはport:port、# はコメント）。-b 必須、コミット対象
.c3c/base-image.txt       # ベースイメージ（例: debian:testing、1行のみ）。-b 必須、コミット対象
```

`env` 以外は任意。`packages.txt`/`requirements.txt`/`allowed-domains.txt` を置かなければ claude-container 同梱のデフォルト（空のフォールバック）が使われる。`node-version.txt`/`codex-version.txt` も置かなければ同梱のデフォルト（固定版。後述）が使われ、こちらは空ファイルが「導入しない」という明示の opt-out になる。`allowed-domains.txt` にはプロジェクトの作業に必要な追加ドメイン（例: pip なら `pypi.org` と、パッケージ本体の実ダウンロード先である `files.pythonhosted.org` の両方— index への到達だけでは `pip install` は完走しない）を書く。ビルド時にイメージへ焼き込まれるため、変更を反映するには `-b` での再ビルドが必要（`env` はこのビルド時焼き込みの対象外 — ホスト固有パスをイメージに含めないため）。

`allowed-domains.txt` は前後のスペース・タブと行末 CR を除き、空行と行頭 `#` のコメント行を無視する。各行は ASCII 英数字・ハイフン・ドットで表すホスト名（各ラベル1〜63文字、ラベルの先頭と末尾は英数字、末尾ドットを除き全長253文字以下）とする。大文字、数字で始まる名前、単一ラベル、末尾ドット、punycode 表記は使える。これは DNS ホスト名の書式上の上限である。世代タグを保存する iptables コメントは255バイト以内のため、UNIX時刻が10桁の現在、実際に許可できる名前は末尾ドット込みで233文字までとなる。タグ長は DNS 解決後に検査し、超過した場合は切り詰めず、該当ルールの適用直前に ERROR で拒否する。行内空白・行内コメント・URL・ワイルドカード・アンダースコア・制御文字・NUL は拒否し、複数の名前を空白削除で結合しない。従来は警告だけで継続していた不正な行も起動エラーになるため、既存設定の行内コメントや複数名を含む行は再ビルド前に修正する。ホスト名の書式は全行を検証してから DNS 解決へ渡すため、書式に反する行があると部分的なリストを使わず ERROR になる。起動時は起動を中止し、更新時は警告して次のサイクルへ進む。ホストの `--check` はこの内容検証を行わないため、変更後は `-b` で再ビルドして起動時の検査結果を確認する。

`allowed-ports.txt` は許可ドメイン（GitHub CIDR・`allowed-domains.txt` 指定分）への到達を許すTCPポートを既定の `443,22` から変更したい場合に使う（`jj1xgo/claude-container#31`）。置かなければ `443,22` が使われる（他の3ファイルと異なり WARNING は出ない — 同梱ファイルを持たない任意機能で、空の意味は `init-firewall.sh` 自身が解釈する）。この制限は許可ドメイン宛のルールにのみ適用され、DNS（53番）とホストネットワーク宛のルールには適用されない（後述「アーキテクチャ」節参照）。`iptables` の `multiport` マッチは最大15枠で、単一ポートは1枠、範囲指定は両端で2枠として数える（範囲内のポート数にはよらない）。例えば単一1件＋範囲7件は15枠で受理し、範囲8件は16枠のため理由付きの ERROR で拒否する。`443` は必ず含めること（api.anthropic.com・api.github.com への到達と起動時の自己検証に必要）、`80` は許可できない（起動時の自己検証が「api.github.com:80 へ到達できない」ことを遮断のプローブに使う）。どちらも範囲指定（`79:81` 等）で含む場合も同様で、違反するとコンテナ起動時に理由付きの ERROR で停止する（`jj1xgo/claude-container#49`）。

各番号は1〜5桁の数字で指定し、6桁以上は先頭ゼロ付きでも書式エラーとする。先頭ゼロは十進数として受理し、iptables へ渡す際に除去する（例: `00443` → `443`、`0120` → `120`）。ポート番号は `1〜65535`、範囲は `1 <= 開始 < 終了 <= 65535` とする。`0`、範囲外の番号、逆順・同値の範囲は起動前のファイアウォール初期化で理由付きの ERROR となる。例えば `443:443` は単一値 `443` に直す。更新モードも同じ検査を行う。ホスト側の `--check` はこのファイルの内容検証を行わないため、変更後は `-b` で再ビルドして起動時の検査結果を確認する。

`node-version.txt` は導入する Node.js のバージョンを決める。claude-container 同梱の `node-version.txt`（default: `24.18.0`。c3c 第2b-2段階から。Codex CLI の npm 導入に必要なため既定で入る）をプロジェクト側で上書きでき、apt の debian:stable では入手できない版（例: 22.x — trixie は 20.x、testing は 22 を飛ばして 24.x）も指定できる。nodejs.org 公式の Linux tarball を取得し、同梱の `SHASUMS256.txt` でチェックサム検証したうえで展開する。**ビルド時ネットワークは無制限のため、`allowed-domains.txt` に `nodejs.org` を追加する必要はない**（`init-firewall.sh` のエグレス制限はランタイムにのみ適用される）。プロジェクト側に**空ファイル**を置くと Node.js を導入しない（明示の opt-out。欠落と同一視して default で埋めることはしない）。起動時と `--check` は `Node.js 版: 24.18.0（採用元: 同梱 default）` / `（採用元: project <path>）` / `なし（… が空 = opt-out）` のように採用元を表示する。同梱 default は `latest` にせず固定版で、更新は claude-container 側の変更（`-b` の再ビルドで反映、既存イメージはドリフト診断で再ビルドを案内）として扱う。

版指定の opt-out には通常の空ファイルを使う（空の通常ファイルへの symlink も可）。`/dev/null` への symlink、リンク先がない symlink、ディレクトリは版指定ファイルとして採用されず、同梱 default が使われる。

`codex-version.txt` は導入する OpenAI の Codex CLI（`@openai/codex`）のバージョンを決める。`node-version.txt` と同じ流儀で、claude-container 同梱の `codex-version.txt`（default: `0.156.0`）をプロジェクト側で上書きでき、**空ファイル**を置くと導入しない（明示の opt-out）。npm 経由でグローバルインストールするため **npm が必要** — 同梱 default どうしなら Node.js（npm 同梱）が先に入る。`node-version.txt` を空にして Node.js を導入しない場合は、`packages.txt` に `nodejs`/`npm` を追加するか、`codex-version.txt` も空にすること。ベースイメージや `packages.txt` で npm が入るかはホスト側の launcher では判定しないため、この組合せでは起動時・`--check` にビルド前の `WARNING` を出す（起動は止めない。npm が無ければビルドがエラーで停止する）。固定バージョン（例: `0.154.0`）の代わりに `latest` と書くと、Claude Code 本体と同じく `-b` リビルドのたびに npm の `latest` dist-tag を再解決してインストールし直す（このケースだけ専用のキャッシュ破棄が働く）。`node-version.txt` は nodejs.org 公式 tarball の SHA256 照合が前提のため `latest` は使えない（バージョン固定のみ）— この非対称は両ファイルの導入方式の違いによるもの。`latest` では上流の変更（サブコマンドの廃止やフラグの変更）が次の `-b` 再ビルドでそのまま入るため、README の手順や利用側プロジェクトの設定が黙って壊れうる（実例: codex-cli は `codex mcp-server` を rust-v0.149.0 で非推奨にし、rust-v0.154.0 で削除した。[`#100`](https://github.com/jj1xgo/claude-container/issues/100)）。手順の安定を要するプロジェクトは固定版を推奨する。コンテナ内からの呼び出し方は後述「Codex CLI をセカンドオピニオンとして使う」節を参照。

`base-image.txt` はベースイメージをホスト環境に合わせたい場合に使う（例: `debian:testing`。内部運用issue参照）。置かなければ既定の `debian:stable` が使われる（他の3ファイルと異なり WARNING は出ない）。許容範囲は **docker.io の debian 公式イメージのみ**（タグは自由、`debian:stable@sha256:<64桁hex>` のような digest pin も可）。範囲外の値は起動を拒否する（fail-closed）。この制限は「セキュリティ境界」ではなく「サポート範囲の宣言・互換性ガード」と位置づけている — `.c3c/` を書き換えられる主体は `packages.txt` 経由で apt の maintainer script をビルド時 root で実行でき、`requirements.txt` 経由の任意 PyPI 名指定でも sdist の `setup.py` がビルド時 root で実行される経路が原理的に残る（PyPI は open publishing のため）。いずれもベースイメージ名だけを縛る防御効果は限定的（Codex 諮問による指摘、内部運用issue参照）。実際の互換性は `Dockerfile.claude` 側のビルド時アサーション（`setpriv`/`tini` の存在・`setpriv --ambient-caps`/`--inh-caps` の受理・apt sources の HTTPS 化）が担保する。ただしこのアサーションは「正直な壊れ方」しか検知できず、悪意を持って `setpriv` 等を偽装するベースイメージは検知できない。`debian:testing`/`debian:sid` のような rolling suite を指定すると、`-b` のたびに未知の apt パッケージ版へ追随するため再現性が下がる — 再現性が必要な場合は日付タグ（`debian:trixie-20260701`）か digest pin を使うこと。値の検証はホスト側の `c3c` スクリプトが行うため、`podman build` を直接実行する経路では効かない。

### 旧 `.claude-container.d/` からの移行

どの呼出名で起動しても（旧名の symlink を含む）、起動 checkout 直下を次の表で探索する（呼出名で結果は変わらない。`--check` も同じ判定を行う）。

| `.c3c` | `.claude-container.d` | 通常起動 / `--check` |
|---|---|---|
| なし | なし | `.c3c` を参照元として同梱の既定値へ fallback（`packages.txt` 等の WARNING は `.c3c/...` の名前で出る）。ディレクトリは作らない |
| ディレクトリ | なし | `.c3c` を採用 |
| なし | ディレクトリ | 旧名を採用し、移行を推奨する `WARNING` を出す（`--check` は `[WARN]` 集計。起動は止めない） |
| 存在 | 存在 | `ERROR` で起動を中止（内容が同じでも、同じ実体への 2 本の symlink でも混ぜない。`--check` は `[FAIL]`） |
| ファイル・リンク先の無い symlink 等 | なし（または逆） | `ERROR` で起動を中止。ビルドや `env` の読み込みより前に止まる |

ディレクトリへ解決できる symlink はどちらの名前でも使える。存在の判定はリンクそのものにも及ぶため、壊れた symlink も「配置あり」として扱う。採用したディレクトリは `env` の読み込み・`packages.txt` 等の解決・境界アセットのハッシュ・ビルドコンテキストのステージング・ランチャーのエラー案内先に一貫して使い、同じ内容なら新旧どちらの名前でも同じハッシュ・同じステージング結果になる（`-b` は不要。`entrypoint.sh` 等の固定アセットはどちらの名前からも上書きできない）。`--check` は対象ごとに診断し、1 つの対象が不正でも次の対象へ進む。設定の選択に失敗した対象では `env`・ガード・ビルド入力の診断を行わず、対象リポジトリには何も書かない。`--clean <ディレクトリ>` と `--clean` は設定の状態に関わらず既存のイメージ・ネットワーク・ビルドコンテキスト・承認記録を清掃する。

Dockerfile・entrypoint のエラー文は新名 `.c3c/` で案内する（c3c 第2b-2段階で更新）。旧名 `.claude-container.d/` を採用しているプロジェクトは、同名のファイルを旧名のディレクトリ内で修正する。

移行は手動で行う（起動時に自動でファイルを移動しない。移行ツールも無い）:

1. 対象プロジェクトを起動していない状態にする（`podman ps` でそのプロジェクトのコンテナが無いことを確認）。
2. バックアップは設定探索の対象外へ置く: `cp -a .claude-container.d /path/outside/the/project/claude-container.d.bak`。**プロジェクト直下に `.c3c` と `.claude-container.d` を並べてバックアップにしない**（二重配置として起動を拒否する）。
3. `mv .claude-container.d .c3c`。Git 追跡対象なら `git mv .claude-container.d .c3c`。`.gitignore` の `.claude-container.d/env` は `.c3c/env` に書き換える（ホスト固有パスを含む `env` を追跡しないため）。`env` の中身はログや Issue に貼らない。
4. `c3c --check <ディレクトリ>` で `[OK]   設定ディレクトリ: .../.c3c` と `.c3c/env あり` を確認する。旧名の `WARNING` が消え、二重配置の `ERROR` が出ないこと。
5. 通常どおり起動する（`c3c claude`・`c3c codex`）。ビルド入力を変えていなければ境界アセットのハッシュは移行前と同じで、`-b` は要らない（ドリフトの `WARNING` が出た場合はビルド入力を変えたときだけ `-b`）。両 CLI を使うプロジェクトは両方の起動を確認する。

元に戻す（ロールバック）: 起動していない状態で `mv .c3c .claude-container.d`（追跡対象なら `git mv`）に戻し、`.gitignore` も戻してから、旧版の `claude-container` を使う。旧版は `.c3c/` を読まないので、戻し忘れると同梱の既定値で起動する（`packages.txt` 等の WARNING が出る）。バックアップを戻す場合も、直下に両方を並べない。

MCP の承認記録・イメージ・起動台帳は起動パス単位、CLI 選択の記憶は Git common directory 単位（非 Git はパスの実体単位）で管理する。いずれも設定ディレクトリの名前には依存しないため移行で変わらない（設定名の変更だけで MCP を再承認済みにはしない — `.mcp.json` や Codex の MCP 定義が変わっていれば従来どおり確認プロンプトが出る）。

## GitHub トークンの配線

設計原則（v4〜、`jj1xgo/claude-container#24`）: **常時使える（export される）権限は最小に、広い権限は明示操作の壁の向こうに、残るリスクは文書で正直に。** GitHub へ書き込む（`gh` CLI・MCP 経由問わず）トークンは、汎用シークレットディレクトリ（`SECRETS_DIR`）1本に集約する。

| スロット | 置き場所 | export | 想定用途・推奨スコープ |
|---|---|---|---|
| メイン PAT | `SECRETS_DIR` 直下（例 `GITHUB_MAIN_PAT`） | されない | push・PR レビュー・Release 作成等。`Contents: write` を含む広い権限を許容する場合はここに置く。gh には後述の明示読み手順で渡す |
| MCP／issues 用 PAT | gh の明示読みだけなら直下（例 `GITHUB_ISSUES_PAT`）。環境変数を必要とする MCP・hook がある場合だけ `export/`（例 `GITHUB_MCP_PAT`） | `export/` 配下のみされる | issue 操作・GitHub 公式 MCP サーバー等。**Issues 限定などスコープを絞ったトークンを推奨**（後述リスク参照） |

2 本目の配置は実際の消費者に合わせて選び、同じトークンを直下と `export/` の両方へ置かない。Issues 用でも常時 export は必須ではない。実装は PAT のパーミッションを検査しないため、「Issues 限定」はファイル名や配置で保証される性質ではなく、GitHub 側で設定・確認する制限である。

**重要**: 「`.c3c/env` を置く場所」と「PATの `Repository access` で選ぶリポジトリ」は別物である。前者はトークンを**使う側**のプロジェクト（例: myproject）、後者は書き込み先リポジトリ（例: claude-container）を指す。myproject から claude-container の Issue に書き込みたい場合、`.c3c/env` は myproject 側に置き、PATの `Repository access` には `claude-container` を選択する — 自分自身（使う側）のリポジトリを登録するわけではない。

fine-grained PAT はトークン単位で、選択した全リポジトリに同一のパーミッションが一律適用される仕様である（リポジトリごとに異なるパーミッションは設定できない）。そのため「自分自身のリポジトリだけ広い権限、他のリポジトリは Issues のみ」としたい場合は、上表のとおりトークンを用途別に分ける。操作系統ごとの可否・パーミッションの全体像は「何ができて何ができないか」節の早見表を参照。

1. GitHub の Settings → Developer settings → Personal access tokens → Fine-grained tokens で新規トークンを作成する。**classic PAT は使わない**（最小の書き込みスコープ `repo` でも全リポジトリのコード読み書きを含んでしまい、漏洩時の被害が過大なため）。設定は用途に応じて選ぶ:
   - Repository access: `Only select repositories` → 書き込み先リポジトリのみ選択（複数選択すると、以下のパーミッションが選択した全リポジトリに一律適用される点に注意）
   - Repository permissions: 必要最小限のみ付与する。MCP／issues 用トークンなら `Issues: Read and write` のみを推奨。メイン PAT に `Pull requests: Read and write` を足すと自リポジトリの PR レビューまで、`Contents: write` を足すと push・PR マージ・Release 作成までコンテナ内から実行可能になる（`Contents: write` を付与しない限り push・マージ・Release作成はホスト側限定のまま維持される）
   - Expiration: 90日以下を推奨
2. ホストにディレクトリを作り（例: `~/.config/claude-container/secrets.d/<project>`）、`chmod 700` する。中に置く各ファイルの**ファイル名がそのままコンテナ内の環境変数名（`export/` 配下のみ）になる**（`^[A-Za-z_][A-Za-z0-9_]*$` に合致しない名前は起動時に WARNING を出してスキップされる）。各ファイルは `chmod 600` し、中身はトークン文字列1行のみ（`export/` では CR・LF が除去されるが、複数行の値は連結されるため非対応。後述の gh 明示読みでは末尾の LF だけが除去されるので、CR や余分な空白を含めない）。各ファイルは実体（通常ファイル）として置くこと — コンテナにはこのディレクトリ単体がマウントされるため、ディレクトリ外を指すシンボリックリンクはコンテナ内でリンク先を解決できず、**警告なしにスキップされる**（既存のトークンファイルを流用したい場合はシンボリックリンクでなく値をコピーする）
3. メイン PAT は `SECRETS_DIR` 直下に置く（例 `SECRETS_DIR/GITHUB_MAIN_PAT`）。Issues 用を gh の明示読みだけで使う場合も直下に置く（例 `SECRETS_DIR/GITHUB_ISSUES_PAT`）。MCP・hook 等が環境変数を必要とする場合だけ `SECRETS_DIR/export/` 配下に置く（例 `export/GITHUB_MCP_PAT`。`export/` ディレクトリ自体も `chmod 700`）
4. ターゲットプロジェクトの `.c3c/env` に `SECRETS_DIR=~/.config/claude-container/secrets.d/<project>` のようにパスを書く。`.c3c/env` はホスト固有のパスを含みうるため gitignore 対象であり、そもそもコミットされない
5. ディレクトリが存在しない場合は起動時にエラーで停止する（fail-closed）。ディレクトリが `700` でない、または中のファイルが `600` でない場合は警告が出る

トークンはホスト上のファイルとしてのみ扱われ、コンテナの `environment:` には渡らない（`podman inspect` 等にも露出しない）。メイン PAT はファイルパスのみが `GITHUB_MAIN_PAT_FILE` として export され、値自体は export されない。`export/` 配下のトークンのみ、ファイル名と同名の環境変数として値ごと export される。**既に環境に存在する変数名（`PATH` 等）と衝突する場合は、既存の値を上書きせず警告を出してスキップする**。

これは汎用の環境変数注入機構であり、GitHub トークンに限らず任意のシークレットを持ち込める。持ち込んだ変数はコンテナ内の全プロセス（Claude 本体・hooks・任意の npm スクリプト等）から読めるため、1コンテナに持ち込むのはそのプロジェクトで実際に使う最小本数に留めること。**`export/` に `GH_TOKEN`/`GITHUB_TOKEN` という名前のファイルを置くと `gh` CLI の ambient 認証が復活する**（本設計の意図に反するため非推奨。明示的な opt-in と理解した上でのみ行うこと。同様の理由でコンテナ内での `gh auth login` の実行も推奨しない）。

**PAT を gh CLI に明示的に渡す**: 次はコンテナ内で、直下の `GITHUB_ISSUES_PAT` を使う例。`OWNER/REPO` は対象リポジトリへ置き換える。ホストの `SECRETS_DIR` はコンテナ内では `/home/node/.config/claude-container/secrets` にマウントされる。

```bash
(
  set +x
  github_pat=$(cat /home/node/.config/claude-container/secrets/GITHUB_ISSUES_PAT) || exit 1
  [ -n "$github_pat" ] || { echo "ERROR: PAT ファイルが空です" >&2; exit 1; }
  GH_TOKEN="$github_pat" gh issue list --repo OWNER/REPO
)
```

メイン PAT を使う場合は `cat` の引数を `"$GITHUB_MAIN_PAT_FILE"` に、最後の gh コマンドを目的の操作に置き換える。ファイルを読めない場合や値が空の場合は gh を実行しない。サブシェル内でトレースを無効にし、値は対象の gh プロセスとその子プロセスに `GH_TOKEN` として渡す。これは不要な環境継承を減らす手順であり、ファイルを直接読めるプロセスからのアクセス制御ではない。この括弧内で値を表示する `echo`・`env` や `set -x` の再有効化を行わない。

**常時 export をやめる場合**: 移動前に `.mcp.json` の `${GITHUB_MCP_PAT}` と hook 等の参照を確認する。MCP を使い続けるなら export 配置を維持する。MCP をやめるなら対応する MCP 設定を外し、hook は明示読みに変更してから、ファイルを直下へ移す。直下でも `GITHUB_MCP_PAT` という名前のままなら用途確認の WARNING が出るため、gh 専用には `GITHUB_ISSUES_PAT` 等の名前を使う。移動だけでは既存プロセスに継承済みの値は消えないので、対象コンテナを終了して起動し直す。配置変更自体にリビルドは不要。非 export 化は漏洩済みトークンの失効・再発行の代わりにはならない。

**設定済みスコープの確認**: **現時点で fine-grained PAT の対象リポジトリ一覧を機械的に取得する手段は存在しない**。GitHub側にも対象リポジトリを一覧で返すAPIは無く（個人アカウント所有リポジトリ向けの同等APIは存在しない。組織所有リポジトリ限定の `GET /orgs/{org}/personal-access-tokens/{pat_id}/repositories` はGitHub App専用でPATでは使えない）、本プロジェクトもPAT設定変更への追従コストを避けるため対象リポジトリ自体を保持しない。したがって個別リポジトリ単位で疎通確認するしかない: 上記の明示読み手順で確認対象のトークンを渡し、`gh api /repos/<owner>/<repo>` を実行し、**private リポジトリに対してのみ** 200/404 がスコープ判定として機能する（200＝アクセス範囲内、404＝範囲外）。**public リポジトリはこの方法で判定できない**: GitHub は public リポジトリのメタデータ（`GET /repos/{owner}/{repo}` とその `permissions` フィールド）をトークンの `Repository access` 設定に関わらず常に200で返すため、公開リポジトリでは到達可否も `permissions` の値もスコープの証拠にならない（実機検証済み。詳細: `jj1xgo/claude-container#13`）。public リポジトリの実効スコープを確認したい場合は、PAT設定画面（Web UI）の `Repository access` 一覧を直接確認すること。実際の書き込みの可否は、承認済みの実作業を行った結果で確認し、権限確認だけのために書き込み操作を追加しない。対象範囲の正本は常にPATの `Repository access` 設定側にある。

**トークンの更新**: 期限が近づいたら GitHub 側でトークンを再生成し、対応するファイルの中身を新しい文字列で上書きするだけでよい。ビルド時に焼き込まれる設定ではなくランタイムマウントなので、リビルド（`-b`）は不要 — 次回起動時に読み直される。

**注意**: 起動時のチェックはファイルの存在とパーミッションのみで、トークン自体が期限切れかどうかは検証しない。期限切れのトークンが入っていてもコンテナは正常に起動し、実際に `gh` コマンドで GitHub API を呼んだ時点で初めて認証エラーになる。気づかず放置しないよう、設定した `Expiration` をどこかにメモしておくこと。

**GitHub 公式 MCP サーバーを使う場合のレシピ**: `gh` CLI でなく MCP 経由で GitHub を操作したい場合、次のように設定する。

1. ターゲットプロジェクトの `.c3c/allowed-domains.txt` に `api.githubcopilot.com` を追加する（ビルド時焼き込みのため `-b` での再ビルドが必要）
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
| `GH_TOKEN_SECONDARY_FILE` | gh の明示読みだけなら `SECRETS_DIR` 直下（例 `GITHUB_ISSUES_PAT`）。MCP・hook 等が環境変数を必要とする場合は `export/`（例 `GITHUB_MCP_PAT`） |
| `SECRETS_DIR/noexport/GIT_PUSH_TOKEN` | `SECRETS_DIR/GITHUB_MAIN_PAT`（push・PR用トークンに統合） |

legacy 変数が設定されたまま起動すると fail-closed で停止し、上記の移行手順が起動ログに表示される。実体ファイルを削除・移動する前に、他プロジェクトから同じファイルを参照していないか必ず確認すること（削除は本移行のスコープ外 — 参照確認が済むまで残す）。

**git push を使う場合（`SECRETS_DIR/GITHUB_MAIN_PAT`）**: デフォルトでは git のリモート操作のうち push は不可（後述「何ができて何ができないか」節）。メイン PAT に `Contents: write` を付与すると有効化できる。

1. GitHub の Fine-grained PAT を作成する。Repository access は push 先リポジトリのみに限定し、Repository permissions で `Contents: Read and write` を付与する（push には `Contents: write` が必要）。GitHub 側の branch protection（レビュー必須化・force-push 禁止等）の併用を推奨する
2. トークン文字列を `SECRETS_DIR/GITHUB_MAIN_PAT`（直下、export されない）という名前のファイルに保存し `chmod 600` する
3. ターゲットプロジェクトの `.c3c/env` に `SECRETS_DIR=...` を設定する（他用途で設定済みなら追加設定不要）
4. `Dockerfile.claude` の変更を伴うため `-b` での再ビルドが必要

起動すると `entrypoint.sh` が `SECRETS_DIR/GITHUB_MAIN_PAT` の存在を検知し `GIT_ASKPASS` を自動設定する（トークンの値自体は export されない。パスのみ `GITHUB_MAIN_PAT_FILE` として export される）。以降、対象リポジトリへの `git push`（**HTTPS リモート限定** — SSH リモートには効かない）は、`git-askpass.sh` がトークンをファイルから都度読んで応答するため、追加の手動操作なしに通る。`git-askpass.sh` は github.com 宛の Username/Password プロンプトにのみ応答する fail-closed 設計で、他ホスト・想定外のプロンプトには応答しない。

このトークンは private リポジトリの fetch/pull にも有効になる（`Contents: Read` 相当を含むため）副作用がある点に注意。また `Contents: write` を持つ同じトークンは前述の明示読み手順で `gh pr merge ...` のような gh CLI の操作にも使えてしまうため、push だけでなく PR マージも「できるが、黙ってはできない」（明示読みという一手間を要する）状態になる点を理解した上で運用すること。

`GITHUB_MAIN_PAT` を検知すると、`entrypoint.sh` は `GIT_CONFIG_*` 環境変数で `credential.helper` を空にリセットする。これは、`GITCONFIG_FILE`（後述）でマウントしたホストの gitconfig に `credential.helper = store` 等の設定が含まれていても、`git-askpass.sh` が都度読んだトークンを `~/.git-credentials` へ平文で永続化させないための対策（マウントされる `~/.gitconfig` は read-only のため `git config --global` での上書きはできず、全 config ファイルより後に適用される `GIT_CONFIG_*` 環境変数がこの目的で使える唯一の手段）。

**force push 対策**: `GITHUB_MAIN_PAT` はコンテナ内からの `git push --force` 等の強制上書きも素通しするため、対象プロジェクトの `.claude/settings.json` に `permissions.deny` で `Bash(git push --force:*)` を追加するのが一次防御になる。ただしこの deny はコマンド文字列の前方一致で判定されるため、フラグ後置形（`git push origin master --force`）・`git -C <path> push --force`・`+refspec` 形式（例: `git push origin +feature:main`）は素通しする既知の限界がある。`--force-with-lease` は `--force` で始まらない別オプションのため `Bash(git push --force-with-lease:*)` を別途追加する必要がある。この見逃し範囲を deny ルールの列挙だけで完全に塞ぐのは煩雑なため、「force push はユーザーの明示承認後のみ」という CLAUDE.md 等の文書ルールを二重の防波堤として併用することを推奨する（利用側プロジェクトでの実機検証を踏まえた知見）。

**コンテナ内 git commit（`GITCONFIG_FILE`）**: ホストで `git config --global user.name`/`user.email` を設定していても、デフォルトではコンテナ内に反映されず `git commit` が `Author identity unknown` で失敗する。`.c3c/env` に以下を書くと解消する。

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
3. 接続先ドメインを `.c3c/allowed-domains.txt` に追加する（ビルド時焼き込みのため `-b` での再ビルドが必要）

**stdio タイプ**（コンテナ内でコマンドとして起動するサーバー）は、この一存では追加できない。`entrypoint.sh` が起動時に `/workspace/.mcp.json` を監査し、`command` フィールドを持つサーバーを検知するとサーバー名・実行コマンドを表示した上で対話確認（TTY 入力）を求める。確認できない場合（非対話起動、または拒否）は起動を中止する（fail-closed）。

この確認を挟む理由: stdio タイプのサーバーは、`npx` 等によるネットワーク越しの取得を経ずリポジトリに同梱されたコードとして実行できるため、http タイプと違ってファイアウォール・再ビルドという既存の壁を通らない。Claude Code 本来の MCP 承認プロンプトは壁に数えない（従来の既定 `--dangerously-skip-permissions` 下で機能しないことを実機確認済み。auto mode 下は未計測。後述「セキュリティモデル」節）ため、この対話確認が唯一の壁になる。**環境変数による opt-out は用意していない**: `.c3c/env` はリポジトリ自身が書けるファイルであり、そこで受け付けるキー（前述「環境変数」節の表）に opt-out 変数を加えれば悪意あるリポジトリも同じ行を書けてしまうため、ゲートとして意味を成さない。

stdio タイプのサーバーをどうしても使いたい場合は、`npx` 等の実行時取得（＝セッション開始のたびネットワーク越しに未検証のコードを取得する経路）でなく、`.c3c/packages.txt` 等によるビルド時焼き込み、またはホスト側インストール＋bind mount（`EXTRA_MOUNT` 等）で導入することを推奨する。**`packages.txt` 経路ではバージョン固定ができない**（`pkg=version` 形式のバージョンピンは allowlist 検証で拒否される）ため、バージョン固定が必要な場合は bind mount 経路を採ること。あわせて、npm レジストリ（`registry.npmjs.org` 等）を `allowed-domains.txt` へ追加しないこと — 追加すると `npx` 経由の実行時取得が成立し、上記の対話確認を毎回強制されるだけでなく、取得するコード自体の検証が効かなくなる。

**TOFU（Trust On First Use）による確認の省略**（claude-container#28）: 対話確認で `y` と回答すると、`c3c` スクリプトが承認時点の stdio サーバー定義のハッシュを、ホスト側 `~/.local/state/claude-container/mcp-approvals/<project>` に記録する（`.mcp.json` 自体やコンテナ内には保存しない — コンテナ側から改変できない場所に置くのが目的）。次回以降の起動では、`.mcp.json` の stdio サーバー定義がこの記録と一致する限り対話確認を自動的にスキップし、定義が変化した場合のみ再度確認を求める。記録はプロジェクトごとに独立しており、`--clean <directory>` で当該プロジェクト分のみ、引数なしの `--clean` で全プロジェクト分をまとめて削除できる。

なお `claude mcp add` によるローカル／ユーザースコープの登録（`~/.claude.json` 側）はこのゲートの対象外である。これはリポジトリ側が制御できないファイルへの登録のため「悪意あるリポジトリの初回起動」という脅威モデルには当てはまらず、各プロジェクトの利用者が自己管理する範囲になる。

## Codex CLI をセカンドオピニオンとして使う

OpenAI の Codex CLI をコンテナ内の Claude Code セッションから諮問・レビュー用のセカンドオピニオンとして呼ぶ場合のレシピ。Codex は `codex exec`（非対話 CLI）として呼び出す。以前はここに Codex を stdio 型 MCP サーバー（`codex mcp-server`）として `.mcp.json` に登録する手順を載せていたが、上流の codex-cli が rust-v0.149.0 で `codex mcp-server` を非推奨にし、rust-v0.154.0（2026-09-09、[openai/codex#42993](https://github.com/openai/codex/pull/42993)）で削除したため、MCP 経路は案内しない（0.153.0 以前に固定すれば動くが非推奨経路のため推奨しない。[`#100`](https://github.com/jj1xgo/claude-container/issues/100)）:

1. Codex CLI は同梱 default（`codex-version.txt`＝`0.156.0`、`node-version.txt`＝`24.18.0`）で既定のイメージに入る（前述「利用側プロジェクトの設定」節）。別の版が必要ならターゲットプロジェクトの `.c3c/codex-version.txt` に固定版または `latest` を書く。`node-version.txt` を空にして Node.js を外す場合は `packages.txt` の `nodejs`/`npm` で npm を用意する
2. ターゲットプロジェクトの `.c3c/allowed-domains.txt` に `chatgpt.com` を追加する。ChatGPT アカウント認証（`auth.json`）を使う Codex は API 呼び出し先を `https://chatgpt.com/backend-api/` にハードコードしており（[openai/codex](https://github.com/openai/codex) `codex-rs/model-provider-info/src/lib.rs` の `CHATGPT_CODEX_BASE_URL` 等）、許可しないとエグレスファイアウォールに阻まれて呼び出しが失敗する
3. ホストに Codex 専用の認証情報ディレクトリを用意し、`~/.codex/auth.json`（ホストで `codex login` 済みのもの）を1回だけシードコピーする。**ホストの実 `~/.codex` を `CODEX_DIR` にそのまま指定しないこと** — auth.json の自動リフレッシュ書き戻しのため rw マウントが必須であり、実ディレクトリを共有するとコンテナ側のコードが `config.toml`（`notify` フック等）を書き換えられ、ホストで Codex を起動した際に任意コマンドが実行される経路になる（詳細は `examples/c3c/env.example` の該当コメント参照）:
   ```
   mkdir -p -m 700 ~/.codex-container
   cp ~/.codex/auth.json ~/.codex-container/auth.json
   chmod 600 ~/.codex-container/auth.json
   ```
4. ターゲットプロジェクトの `.c3c/env` に `CODEX_DIR=~/.codex-container` を設定する（`-b` 不要、ランタイムマウント）
5. コンテナ内の Claude Code セッションから、通常のコマンドとして呼ぶ（`.mcp.json` には登録しない）:
   ```bash
   codex exec --sandbox read-only -C /workspace "<依頼文>"
   ```
   `--sandbox read-only` は省略しない（呼び出し時の `--sandbox` が `config.toml` の値に勝つ。諮問・レビュー用途は読み取り専用で足りる）。`-C /workspace` で作業ルートを明示する（Codex は作業ルートの `AGENTS.md` を指示として読むため、起点を固定する）。最終応答だけをファイルに取りたい場合は `-o <ファイル>` を足す。`/workspace` が git リポジトリでない場合は `--skip-git-repo-check` が必要
6. `-b` での再ビルドが必要（`codex-version.txt`/`allowed-domains.txt` はいずれもビルド時焼き込み設定のため）

**運用上の注意**: Codex は作業ルートの `AGENTS.md` を指示として読む。MCP 経路では `cwd` の渡し忘れで意図しない `AGENTS.md` が拾われる問題があった（[openai/codex#12128](https://github.com/openai/codex/issues/12128)）。`codex exec` でも起点が変われば同じことが起きるので、`-C /workspace` を毎回明示する運用を徹底すること。また auth.json のリフレッシュフローには既知の不具合報告（[openai/codex#15502](https://github.com/openai/codex/issues/15502)）があり、この領域は枯れていない可能性がある点に留意する。

## Codex CLI を対話で使う

`--agent codex <ディレクトリ>` は、Claude と同じ外側境界（マウント・capability 剥奪・エグレス制限・`.c3c/env` の許可リスト）の中で、Codex CLI の標準の対話 UI を起動する。無指定と `--agent claude` は従来どおり Claude Code で、既存の起動フロー・`.mcp.json` ゲート・承認記録は変えない。未知の値・値の欠落・複数指定は終了コード 2 で止まり、別の CLI へ黙って切り替えることはない。`--read-only` は `--agent codex` 専用で、Codex を read-only sandbox で起動する（諮問・レビュー用。通常は workspace-write）。`--agent` は `--clean`/`--clean-missing` と併用できない（清掃は両 CLI の記録を対象にする）。

**前提**（`--check --agent codex <ディレクトリ>` が静的に診断する）:

- `.c3c/env` に `CODEX_DIR`（Codex 専用の認証ディレクトリ。ホストの実 `~/.codex` は拒否）。専用ディレクトリで新規に ChatGPT ログインを行う運用も選べる（認証ファイルの表示・解析・ホストからの自動コピーは launcher が行わない）
- `codex-version.txt` は固定版か `latest`（未指定なら同梱 default の `0.156.0`。npm が必要で、同梱 default の `node-version.txt` か `packages.txt` の `nodejs`/`npm` で導入）。起動時審査は Codex の版に依存しない。プロジェクト側の空ファイル（opt-out）は起動を中止する。起動時審査はイメージ内の python3（3.11 以上。`tomllib` を使う）で行う
- `allowed-domains.txt` の `chatgpt.com` 等、前節と同じ通信許可

**専用 home と新規ログイン**: `CODEX_DIR` は認証だけでなく、コンテナ用の `config.toml`・履歴・CLI の状態も保存する rw 領域で、コンテナ内では `/home/node/.codex` に固定される。ホストの実 `~/.codex` の設定・認証は共有しない。ホスト用と同じ設定が必要なら、コンテナ用にも明示的に設定する。専用ディレクトリは mode 0700、認証ファイルは 0600 で管理し、認証の本文をログやリポジトリへ保存しない。

既存認証のコピーを使わず、専用 home をマウントしたコンテナ内で新たに ChatGPT へログインする場合の CLI 操作は次のとおり。

```bash
codex -c 'cli_auth_credentials_store="file"' login --device-auth
codex -c 'cli_auth_credentials_store="file"' login status
```

CLI が表示する公式 HTTPS URL をホストのブラウザで開き、一時コードを利用者自身が入力する。デバイス認証なので localhost callback のポート公開は行わない。URL・コードの表示だけで成功とせず、CLI の成功終了と `login status` の ChatGPT ログイン表示を確認する。この操作は [第0B-4の認証試験](docs/superpowers/plans/2026-09-20-c3c-phase0b4-results.md) で成立したが、その試験は既存イメージと認証用 shim を使っており、現在の `--agent codex` 起動全体の受入とは別である。期限切れ認証の refresh も、この成功だけでは確認できない。

**起動フロー**: 通常の初期化とガードの後、(1) イメージが無ければ `-b` なしでも明示ビルドし（イメージがあり `-b` なしならビルドしない）、(2) 実際に起動するイメージの固定 label `io.c3c.codex-audit-protocol=2` を確認する。label が無い・値が異なる旧イメージでは検査用コンテナも本起動も行わず `-b` を案内する。(3) 同じマウント・作業ディレクトリの検査用コンテナ（非 TTY、`compose.codex-preflight.yml`、stdin は `/dev/null`）を起動し、コンテナ内の `codex-mcp-audit.py` がリポジトリ同梱の `/workspace/.codex/config.toml` を読んで、enabled な stdio 定義の canonical hash と表示用情報だけを 1 つの JSON 文書として返す。Codex CLI・agent・MCP の command はこの段階で起動しない。(4) launcher は stdout 全体が対応 protocol の JSON 1 文書であることを検証し（余分な出力・破損・protocol 違いは拒否）、ホスト側の承認記録 `~/.local/state/claude-container/mcp-approvals/codex/<project>/project-config.json` と照合する。初回・変更時は対象の名前・command・args・cwd・env のキー名・env_vars・environment（指定時）を表示して `[y/N]` で確認し（env の値・HTTP header は表示しない）、拒否・TTY 無し・EOF では Codex を起動しない。対象 0 件（ファイルが無い場合を含む）は空定義として確認なしで記録する。(5) 本起動でも同じファイルを読み直して hash を再計算し、`:ro` で渡した記録と一致した場合だけ Codex へ進む（検査と本起動の再照合の間に審査対象の定義が変われば拒否）。

**審査の範囲と限界**: 対象はリポジトリ同梱の `/workspace/.codex/config.toml`（第三者が内容を制御しうる project 設定）の `mcp_servers` で、enabled な stdio 定義を hash して確認する。`http_headers_helper` を持つ enabled な定義は、ローカル command の実行定義を審査できないとして起動を拒否する（定義を無効化すれば起動できる）。helper の無い HTTP 型は外側のエグレス制限に委ね、URL 変更は再承認の対象にしない。hash には名前・command・args・cwd・env の値・env_vars・environment_id を含め、無効な定義と timeout 等の診断値は含めない。同じファイルで plugin が有効化されていれば（`enabled = false` は通す）、plugin の中身を c3c が読めないため確認の前に起動を拒否する。marketplace が定義されていれば、plugin の取得元を差し替えうるため同じく拒否する。未知の key・値の型違い（無効な定義も含む）・壊れた TOML・command と url の併記は判定不能として停止する。`CODEX_DIR` の user 設定と plugin キャッシュ・user 層で有効化した plugin は審査しない（Claude 経路の `~/.claude.json` と同じ扱い。「セキュリティモデル」節の #29 の線引き）。そのため、セッションが `CODEX_DIR` の `config.toml` に MCP を書き足しても次回起動の確認は出ない。Codex は設定層を table ごとに深く merge するので、project の `url` だけの定義が user 層の同名定義の宛先を変えたり、project の `command` だけの定義に user 層の `args`・`env` が合わさったりしうる（確認表示は project 設定の内容だけ）。網羅性（project 層の探索規則、MCP・plugin・marketplace 以外に repo から実行経路を持ち込める設定が無いこと、許可 key の集合）は codex-cli 0.156.0 で確認した。`latest` 等で入った別の版がリポジトリ設定から新しい実行経路を取り込んでも追えない。起動後の設定変更・再接続は Codex の標準機能で、継続監視はしない（既存 Claude の TOFU と同じ限界）。ファイアウォールの初期化は検査と本起動で 2 回走る。固定の trust override（`projects={"/workspace"={trust_level="trusted"}}`）は本起動に渡すため、repo 側 `.codex/config.toml` の hooks・sandbox 設定等も有効になるが、MCP 以外の定義を c3c が承認した意味にはならない（hooks は Codex 自身の個別確認に委ねる）。sandbox と approval の CLI 指定は固定するが、追加の書込み先や exec policy などは native 設定の影響を受ける。実行ファイルや script 自体の内容の改変は、この定義 hash では検出しない。第1段階では `~/.claude.json` と `~/.claude` の rw 共有はそのまま残るため、Codex セッションからも Claude の認証・履歴等が見える（CLI ごとの認証隔離は未達成。全面分離は後続段階）。審査範囲と隔離の限界は [SECURITY-CLAIMS C-3](SECURITY-CLAIMS.md#c-3)・[C-4](SECURITY-CLAIMS.md#c-4) を参照。

**sandbox の bubblewrap（#145）**: Codex の Linux sandbox は PATH 上で最初に見つかった `bwrap` を調べ、必要な機能があればそれを使う。c3c はビルド時に Codex 同梱の bubblewrap（npm が導入した `@openai/codex` の対応アーキテクチャの `codex-resources/bwrap`）を指す固定 symlink `/usr/local/libexec/c3c/codex-bwrap/bwrap` を作り、`entrypoint.sh` の Codex 経路だけがこのディレクトリを PATH の先頭へ加える。画像ライブラリ等の間接依存でシステム版（`/usr/bin/bwrap`）が入っていても、Codex は同梱版を選ぶ。システム版は削除・移動・書換えをしない。Claude 経路とイメージ全体の `PATH` は変わらない。

- **直る仕組み**: 同梱版で新しい `/proc` のマウントが失敗すると、Codex はその失敗を認識して外側コンテナの procfs を引き継ぐ方式へ切り替える。システム版 0.12.0 のエラー表記はこの認識に一致しない（[調査記録](docs/codex-proc-investigation.md)）。つまり新しい procfs のマウントを成功させる変更ではない。上流が安全な既定とする新しい procfs とは保護範囲が異なる。実測（x86_64、Codex 0.156.0）では、sandbox 内から外側コンテナのプロセス一覧と `cmdline` が見えた。Codex の node ラッパーと本体の `environ` は open できなかった。詳細は調査記録の「#145 の受入」を参照する。
- **子プロセスへの影響**: PATH は Codex の子プロセスへ継承されるので、Codex から名前で `bwrap` を呼ぶと同梱版になる。MCP stdio の `command = "bwrap"` も同様である（承認記録はコマンド文字列で照合し、解決される実体は PATH で決まる）。システム版が必要な呼出しは `/usr/bin/bwrap` と絶対パスで書く。c3c を経由しない独立起動や `podman exec` には、この PATH 変更は自動では適用されない。
- **対象外の設定**: Codex は `shell_environment_policy` に従って子プロセスと sandbox helper の環境を作り直す。c3c の保証は、entrypoint が審査（snapshot / verify）と本起動へ同じ PATH を渡すところまでで、既定の policy を前提にする。`set.PATH`・`exclude`・`inherit` 等で PATH を変える設定では、選ばれる bwrap が変わりうる（c3c は設定を強制上書きしない）。
- **信頼の置き方**: PATH 経由の選択では、上流の同梱版専用の起動経路（ビルド時 digest との照合と `/proc/self/fd` 経由の exec）を通らない。c3c は独自の hash 固定や起動時 checksum を加えず、npm による導入物と root 所有のイメージを信頼する。ビルド時に、help の必須 4 項目（`--as-pid-1`・`--perms`・`--argv0`・`--ro-bind-fd`）を検査する。あわせて、リンク・実体・全親ディレクトリが root 所有で、group/other から書き込めないことも検査する。`test-build.sh` は最終イメージでも node から書き込めないことを確認する。root やイメージ自体の改ざんは防御対象外で、上流の digest 検証と同等の保証ではない。
- **旧イメージ**: `entrypoint.sh` はビルド時にイメージへ焼き込まれるため、#145 より前にビルドしたイメージは旧 entrypoint のまま起動し、従来どおりシステム版が選ばれて `/proc` のエラーになりうる。`--check` と通常起動は境界アセットのドリフトを WARNING で示す。`c3c codex -b <ディレクトリ>` で再ビルドする。
- **起動時の検査**: 修正後のイメージの Codex 経路は、固定リンクが無い・壊れている・実行できない場合に、審査より前に `ERROR: Codex 同梱の bubblewrap がありません。-b で再ビルドしてください。` で止まる。上流の PATH 探索は、存在しない・実行できない候補を飛ばして次の候補（`/usr/bin/bwrap`）を選ぶので、この検査はシステム版へ黙って戻ることを防ぐ fail-closed である（help が不適合な先頭候補の場合は、上流は同梱版の経路へ進む）。

**`--check` と `--clean`**: `--check --agent codex` は検査用コンテナを起動せず、`CODEX_DIR`・版指定・イメージの label・承認記録の存在と形式だけを報告し、実効 MCP の動的照合は `not run` と明示する（承認済みとは報告しない）。`--clean <ディレクトリ>` はそのプロジェクトの Claude の記録と Codex の記録ディレクトリ全体（過去版を含む）を削除し、他プロジェクトは残す。`--clean` は記録全体を削除する。

実イメージと専用 ChatGPT 認証で、非 TTY protocol 分離、承認・変更拒否、対話作業と `/resume`、hook の個別承認後の実行まで確認した。共有ノートの Markdown は読めるが、既定の `workspace-write` sandbox では `/shared` への書込みは拒否された。CLI ごとの自動 memory の同等性や、期限切れ認証の refresh まで確認した意味ではない。最終レビューと残る受入条件は [第1段階の検証記録](docs/superpowers/plans/2026-09-20-c3c-phase1-results.md) を参照。

## c3c 入口（CLI の選択と記憶）

`c3c` が唯一の入口（通常ファイル）で、呼出名に関わらず次の引数解釈になる（c3c 第2a段階で導入、旧入口 `claude-container` は削除済み。[増分移行の段階計画](docs/superpowers/specs/2026-09-20-c3c-incremental-design.md) 第2段階 2a）。`CLAUDE_CONTAINER_*` の env キー・イメージ名・state directory・承認記録・コンテナ内のパスはこの段階では変えない。設定ディレクトリは第2b-1段階で `.c3c/` を標準にした（旧名との互換と移行手順は前述「利用側プロジェクトの設定」節。入口名で探索結果は変わらない）。

| 入力 | 動作 |
|---|---|
| `c3c claude [<dir>]` / `c3c codex [<dir>]` | 明示した CLI。dir 省略時は現在のディレクトリ |
| `c3c [<dir>]` | 記憶があれば使用（`INFO: 前回の選択: codex` のように表示）。なければ対話選択 |
| `c3c --agent codex [<dir>]` | 既存オプションの別表記。サブコマンドとの重複は同値でも終了コード 2 |
| `c3c --read-only [<dir>]` | 最終的に選ばれた CLI が Codex の場合だけ有効。Claude なら終了コード 2 |
| `c3c --check [<dir>...]` | 選択待ちをしない・記憶を更新しない。無指定は既存の台帳全件診断、CLI 無指定は現行どおり Claude の診断 |
| `c3c codex --check <dir>` / `c3c --agent codex --check <dir>` | 既存の Codex 診断。記憶による選択はしない |
| `c3c --clean [<dir>]` / `c3c --check --clean-missing [<dir>...]` | 既存の清掃範囲。選択・記憶の更新なし、CLI の指定は終了コード 2。記憶は削除しない |

- `c3c` では最初の位置引数の `claude` / `codex` だけをサブコマンドにする。同名のディレクトリは `./codex` や `-- codex` と書く。`--` 以降はすべて位置引数。通常起動と `--clean` のディレクトリは最大 1 件、未知のオプションは終了コード 2（旧入口の「未知オプションを位置引数として扱う」解釈は削除済みで、旧名の symlink から呼んでも同じ）。
- **初回選択**: 記憶が無いとき `/dev/tty` から `1`（Claude）か `2`（Codex）を 1 回だけ読む（stdin は消費しない）。不正値・EOF は終了コード 2、Ctrl-C は 130、端末が無い（パイプ・cron 等）場合は待たずに終了コード 2 で `c3c claude <dir>` / `c3c codex <dir>` の明示指定を案内する。失敗後の再プロンプトや別 CLI への自動 fallback は無い。
- **記憶の単位**: 同じ Git リポジトリ（`git rev-parse --git-common-dir` の実体が同じ。main checkout・linked worktree・symlink 別名・リポジトリ内のサブディレクトリは同じ単位、別 clone は別）。非 Git ディレクトリはパスの実体単位。リポジトリを移動すると新しい記憶になり再選択する（旧記憶の探索・移し替えはしない）。既存のイメージ・承認記録・起動台帳の識別（起動パス単位）はこの変更で変えない。
- **記憶の保存先と形式**: `~/.local/state/claude-container/agent-preferences/<sha256>.json`（directory 0700・file 0600、内容は `{"schema":1,"agent":"codex"}`）。ホスト専用の `agent-preference.py` が Git 識別・検証・原子的保存を担当し、`c3c` からだけ呼ばれる。`.c3c/env` やシェル環境から保存先・値を変えることはできない。symlink・非通常ファイル・4096 byte 超・未知の値は不正として扱い、不正な記憶は WARNING の後に初回選択へ進む（明示指定なら不正な記憶を無視して起動する）。
- **更新時点**: 本起動の `podman compose run` が終了コード 0 で戻った後だけ更新する（「最後に正常終了した CLI」の記憶。起動直後のクラッシュは記憶しない）。preflight・ビルド・承認拒否・中断・CLI の非ゼロ終了では旧値を保持し、launcher の終了コードは常に本起動の終了コードになる。保存に失敗しても WARNING だけで終了コードは変えない。同時セッションは最後に正常終了した書込が勝ち、JSON が部分書込になることはない。
- **記憶が使えないとき**: Python 3 が無い、祖先に `.git` があるのに Git として解決できない（壊れた gitfile・権限不足・`--path-format=absolute` 非対応の古い Git 等）場合、明示指定なら WARNING を出して記憶せずに起動し、無指定なら明示指定を案内して終了コード 2 で止まる（別リポジトリの記憶へ誘導しない。継承した `GIT_DIR` 等の `GIT_*` は Git 子プロセスへ渡さず、system/global 設定も無効にして対象ディレクトリから解決する）。記憶した CLI がガード（`CODEX_DIR` 未設定・`codex-version.txt`・イメージの label）で使えない場合は既存の理由に加えて明示再選択のコマンドを案内して終了する。
- **終了コード**: 引数の誤り・選択の不成立は 2、初回選択の Ctrl-C は 130、ガードによる中止は従来どおり 1、それ以外は本起動の終了コード。

実 Podman・実認証での対話受入は 2026-09-21 に実施し、Claude の `/exit`・Ctrl-D ×2（短い間隔で 2 回）と Codex の `/quit`・Ctrl-C ×2 で compose と launcher の終了コードが対で 0 になり記憶が更新されること、`c3c` が前回の CLI を採用すること、非ゼロ終了・中断では記憶が変わらないことを確認した（[第2a段階の検証記録](docs/superpowers/plans/2026-09-21-c3c-phase2a-results.md)）。日常利用・認証 refresh・`/resume` はこの確認に含まない。

## アーキテクチャ

主要ファイルが連携して動作する。

- **`c3c`**（bash）— エントリーポイント（唯一の入口。旧 `claude-container` は削除済みで、呼出名に関わらず前述「c3c 入口」節の解釈になる）。絶対パスを解決し、ターゲットプロジェクトのディレクトリ名（basename）をサニタイズした文字列に絶対パスの sha256 先頭8文字を付与した `PROJECT_NAME` を算出する（例: `myproject-3f2a9c1b`）。これによりイメージ名（`localhost/<PROJECT_NAME>_claude-auth-workspace`）とビルドコンテキストのステージング先（`.build-context/<PROJECT_NAME>/`）をプロジェクトごとに分離し、`podman compose -p "$PROJECT_NAME"` でプロジェクト名を明示する。以前は全プロジェクト共通の固定イメージ名・固定ステージング先だったため、異なるプロジェクトを交互にビルドすると後勝ちで上書きされる問題があった。起動 checkout 直下の設定ディレクトリ（`.c3c/`、旧 `.claude-container.d/`）を `select_project_conf_dir()` で 1 つに決め（両方あれば中止。前述「利用側プロジェクトの設定」節）、その `env` の `KEY=VALUE` 行のうち許可リストのキーだけを読み込み、`TZ` を自動検出した上で `CONTEXT` / `CLAUDE_CONTAINER_DIR` を設定して `podman compose run` に委譲する（`--env-file /dev/null` を付け、対象プロジェクト直下の `.env` は補間に使わない）。`-b` 指定時は `podman compose build` を `run` とは別ステップで実行する — `run --build` はビルド失敗時に既存の古いイメージへフォールバックしてしまう（fail-open）ため、分離して失敗時は起動へ進ませない（fail-closed）。ビルド前に、プロジェクト側の `.c3c/packages.txt`・`requirements.txt`・`allowed-domains.txt`・`node-version.txt`・`codex-version.txt`（無ければ claude-container 同梱のデフォルト。後 2 者は固定版の default で、プロジェクト側の空ファイルは opt-out としてそのままステージする）・`allowed-ports.txt`（無ければ空ファイルを都度生成。同梱のデフォルトファイルは持たず、WARNING も出さない）と `entrypoint.sh`・`init-firewall.sh`・`ipv6-firewall.py`・`firewall-refresh.py`・`codex-mcp-audit.py`・`git-askpass.sh`・`validate-build-input.sh`・GitHub meta スナップショット（後述）をこのプロジェクト専用の `BUILD_CONTEXT_DIR` に集約する（`-b` 指定時、またはイメージ未ビルド時のみ実行）。`--clean <directory>` はそのプロジェクト分のイメージ・ネットワーク・ビルドコンテキストのみを、`--clean`（引数なし）は実在する claude-container イメージ全てを走査して全プロジェクト分を削除する（レガシーの単一共有イメージ `localhost/claude-container_claude-auth-workspace` も同じ命名パターンで検出されるため、旧バージョンからの移行時は `--clean` の実行だけで回収できる）。
- **`compose.yml`** — サービス `claude-auth-workspace` を定義。ビルドコンテキストは `${BUILD_CONTEXT_DIR}`（上記でステージングされたディレクトリ）、Dockerfile は `${CLAUDE_CONTAINER_DIR}/Dockerfile.claude` を参照する。ホストの `~/.claude.json` と `~/.claude/`（認証・設定）、対象ワークスペース（`/workspace`）、`/etc/localtime`（タイムゾーン）をマウントする。`userns_mode: keep-id` でコンテナ内ファイルのオーナーをホストユーザーに合わせる。`cap_add` で `NET_ADMIN`/`NET_RAW` を付与し、`init-firewall.sh` がコンテナのネットワーク名前空間に iptables ルールを設定できるようにする（rootless podman + `userns_mode: keep-id` ではこれらが非root ユーザー `node` の ambient set にも入り全子プロセスへ継承されるため、`Dockerfile.claude` の `ENTRYPOINT`（次項）で剥奪する。後述「セキュリティモデル」節参照）。既定の `sysctls` は `net.ipv6.conf.{all,default}.disable_ipv6=1` で IPv6 を無効化する。IPv6 を明示的に有効にした場合は `compose.ipv6.yml` でネットワークと sysctl を切り替える（「IPv6 を任意で有効にする」参照）。ホストで install した plugin をコンテナ内で読み込めるよう、`compose.plugins-alias.yml` でホストの `~/.claude/plugins` をホストと同じ絶対パス（例 `/home/<host user>/.claude/plugins`）にも `:ro` で重ねる（`c3c` の `guard_plugins_alias()` が条件を満たすときだけ追加する固定 override。後述「何ができて何ができないか」節の plugin の項と「セキュリティモデル」節の限界 (7) を参照。[`#98`](https://github.com/jj1xgo/claude-container/issues/98)）。`SHARED_MOUNT_HOME_ALIAS=1` のときは `compose.shared-home.yml`（`~` 配下の同じ相対位置）と `compose.shared-host.yml`（ホストと同じ絶対パス）で `SHARED_MOUNT` の実体を `:ro` で重ね、`AGENTS_DIR` のときは `compose.agents.yml` で `/home/node/.agents` に `:ro` で付ける（いずれも `c3c` の `guard_shared_home_alias()`・`guard_agents_dir()` が値を検証したときだけ追加する固定 override。前述「ホストの指示ファイルとスキルをコンテナ内で解決する」節。[`#99`](https://github.com/jj1xgo/claude-container/issues/99)）。`CODEX_DIR` を設定した場合は Codex CLI の認証情報ディレクトリを rw でマウントする（他のオプトインマウントと異なり `:ro` を付けない — auth.json のトークンリフレッシュ書き戻しのため。前述「Codex CLI をセカンドオピニオンとして使う」節参照）。起動する CLI は `CC_AGENT`（既定 `claude`）・`CC_CODEX_START_MODE`（既定 `run`）・`CC_CODEX_READ_ONLY`（既定 `0`）の environment で渡し、`c3c` が CLI 引数から導出した値だけを export する（`.c3c/env` では設定できない）。Codex の承認記録は `${CODEX_MCP_APPROVAL_FILE:-/dev/null}` を `/etc/claude-container/codex-mcp-approved.json` に `:ro` で載せる。`--agent codex` の検査用コンテナは `compose.codex-preflight.yml`（`tty: false` / `stdin_open: false` だけの固定 override）を重ねて起動する（前述「Codex CLI を対話で使う」節）。
- **`Dockerfile.claude`** — 既定 `debian:stable`（`.c3c/base-image.txt` で上書き可、前述「利用側プロジェクトの設定」参照。`FROM` は `COPY` より先に評価されるためファイルを直接読めず、`ARG BASE_IMAGE` 経由で受け取る）をベースにビルド。`ca-certificates` を HTTP でインストール後、apt ソースの全 URI を HTTPS に書き換えてから残りのパッケージを取得する（ホスト名リテラルではなく結果ベースで書き換えるため、ミラーが異なっても無言で no-op にならない）。固定 apt レイヤーの直後に、ベースイメージ可変化に伴うビルド時アサーション（`setpriv`/`tini` の存在・`setpriv --ambient-caps`/`--inh-caps` の受理・apt sources に `http://` が残っていないこと）を fail-closed で実行し、境界機構の土台が壊れたまま静かにビルドが成功する事態を防ぐ。Claude Code は公式 native installer（`curl -fsSL https://claude.ai/install.sh | bash`）でインストール。非 root ユーザー `node`（UID 1000、明示的に作成）で動作し、`CMD ["/usr/local/bin/entrypoint.sh"]`（次項参照。root 所有の `/usr/local/bin` に境界アセットとして配置され、node からは書き換えられない）を実行する。`node:24`（約 1.1 GB）から切り替えた理由: native installer は glibc のみ依存で実行時に Node.js を必要としないため、軽量な Debian ベースで十分。slim ではなく full 版を使う理由: full 版には `ca-certificates` 等の基本パッケージが含まれており apt 周りの初期設定が最小限で済む。`ENTRYPOINT` は `setpriv --ambient-caps=-all --inh-caps=-all /usr/bin/tini --` で、`tini` の起動前に ambient/inheritable capability を全プロセスツリーから剥奪する（`setpriv` は exec するため居残らず、tini は PID1 のまま）。これにより `compose.yml` の `cap_add` が非root ユーザーの ambient set にも入る問題（前項参照）を打ち消し、`NET_ADMIN`/`NET_RAW` の実消費者を `sudo` 経由の `init-firewall.sh`（root、bounding set 由来）のみに限定する。tini を PID1 に据えるのは、claude 自身が PID1 だと、PID1 に再親付けされた子プロセス（ファイアウォール更新ループの sudo 補助プロセス等）が reap されずゾンビとして蓄積し、さらに claude が終了時にハングした場合（2026-07-02 に実障害: ホストカーネルの workqueue Oops により kill 不能な D 状態スレッドが残存）は PID1 自体が reap 不能なゾンビとなり、crun がシグナルを配送できず（`crun kill ... failed` / "No such process"）`podman stop` でもコンテナを回収できなくなる。tini を PID1 に置くことで reap と `podman stop` が機能し続ける（カーネル側のハング自体は tini でも防げない）。`tini` は `packages.txt` に入れず Dockerfile 固定のパッケージ行に含める — プロジェクト側 `.c3c/packages.txt` で上書きされて消えるのを防ぐため。`node-version.txt` ブロックの直後には、同じ宣言的ファイルの流儀で Codex CLI（`@openai/codex`）を npm 経由で導入するレイヤーがある（`codex-version.txt` で指定。両ファイルとも同梱 default を持ち、空ファイルは導入しない opt-out。npm 不在時はビルドをエラーで止める。詳細は内部運用issue参照）。`packages.txt`/`requirements.txt` の取り込みも `validate-build-input.sh` による allowlist 検証を `apt-get`/`pip3` の実行より前に置く同格の fail-closed 検証で、setpriv/tini アサーションと同じく境界機構の土台が壊れたまま静かにビルドが成功する事態を防ぐ（前述「利用側プロジェクトの設定」参照）。
- **`entrypoint.sh`** — コンテナの `CMD`（PID1 は上記 tini、このスクリプトと `exec` 先の claude はその子として動く）。起動時に `init-firewall.sh` でエグレス制限を適用し（失敗時は起動を中断）、非特権の `firewall-refresh.py` をバックグラウンドで開始（各更新後15秒待機、状態記録とログ上限は下記参照）したうえで `claude --permission-mode auto`（Claude Code の auto mode。引数を受理しない版では起動失敗のまま止め、auto が利用できないセッションでは Claude Code 本体が Manual に戻す。いずれも旧既定の `--dangerously-skip-permissions` で再試行しない）を起動する。あわせて `/workspace/.mcp.json` を監査して stdio タイプの MCP サーバーを検知した場合は対話確認を要求する（fail-closed。詳細は「MCP サーバーの追加」節参照）。`CC_AGENT=codex` のときは、同じ firewall 適用の後、秘密 export より前に固定の `CODEX_HOME=/home/node/.codex` と CLI 実体 `/usr/local/bin/codex`（npm global bin）を確定し（`secrets/export/` の `CODEX_HOME`・`HOME`・`PATH` では差し替えられない）、秘密 export を完了してから `/workspace` を基点に `codex-mcp-audit.py`（root 所有の境界アセット）で `snapshot`（`CC_CODEX_START_MODE=preflight`: protocol 1 文書だけを起動時に確保した元 stdout へ出して終了）または `verify`（`run`: `:ro` の承認記録と一致した場合だけ `codex --sandbox workspace-write|read-only --ask-for-approval on-request -c 'projects={"/workspace"={trust_level="trusted"}}'` を `exec`）を行う。`.mcp.json` の Claude 用ゲートは Codex 経路では使わない。`CC_AGENT` の未知値・空文字、Codex 経路の `CC_CODEX_START_MODE`/`CC_CODEX_READ_ONLY` の不正値は firewall 適用前に停止し、Claude へ fallback しない。Claude 起動時、launcher は `CC_CODEX_START_MODE` を空文字で渡し、entrypoint はこの Codex 専用値を参照しない。
- **`init-firewall.sh`** — コンテナ起動時に root（sudo）で実行されるエグレス制限スクリプト。Anthropic 公式 devcontainer の同名スクリプトの移植で、iptables により「許可したドメイン以外への外向き通信を遮断」する（deny-by-default）。Claude Code に必要なエンドポイント（api.anthropic.com・GitHub 等）とプロジェクト指定の `allowed-domains.txt` のみ許可する。許可ドメイン宛のルール（GitHub CIDR・タグ付きドメインルール）はさらに TCP ポートを `allowed-ports.txt` で指定した範囲（既定 `443,22`）へ限定する（`jj1xgo/claude-container#31`）。この制限は許可ドメイン宛のルールにのみ適用され、DNS（53番、指定リゾルバ限定）とホストネットワーク宛のルール（ゲートウェイ単一IPのみ許可、`/24` 全体ではない）は対象外（それぞれ別の理由でスコープが絞られているため）。GitHub IP レンジは起動時にライブ取得せず、ビルド時に焼き込まれたスナップショットを読み込むだけ（詳細は下記「GitHub meta スナップショット」参照）。設定後に example.com へ到達**できない**こと・api.github.com / api.anthropic.com へ到達**できる**こと・許可ドメイン上の非許可ポート（api.github.com:80）へ到達**できない**ことを自己検証する（GitHub 側は API クォータを消費しない TCP 接続確認）。失敗時はコンテナを起動しない（fail-closed）。ただし、許可ドメイン（`allowed-domains.txt` 指定分を含む）が恒久的に存在しない場合（NXDOMAIN）は警告に留め起動を継続する（一時的な解決失敗は従来どおり fail-closed）。DNS の A 応答が `0.0.0.0/8`・`127.0.0.0/8` の場合も、警告してその IP の追加・更新をスキップし、それだけでは起動を失敗させない。同じ応答内の他の IP や次のドメインは処理を続ける。既存の該当ルールは通常の約3分の猶予期間を経て削除する。DNS が返した private / link-local には、内部ホストの明示的な許可に使うため従来どおり許可ルールを追加する。loopback・ホストゲートウェイの別ルールによる許可も維持する。既定の IPv4 モードでは IPv6 を `compose.yml` の `sysctls` で無効化するのが主対策だが、それが効かない環境向けに本スクリプト自身も `/proc/sys/net/ipv6/conf/*/disable_ipv6` への書き込みをフォールバックとして試みる（失敗しても警告のみで起動は継続する）。いずれの結果にかかわらず、既定モードの `ip6tables` による IPv6 全遮断は最終防衛線として維持する。IPv6 有効時は専用の `ipv6-firewall.py` が AAAA と IPv6 CIDR の許可リストを管理し、この全遮断処理は実行しない。許可ドメインの IP は `entrypoint.sh` が起動する `firewall-refresh.py` により各更新後15秒待機で再解決され（`init-firewall.sh --refresh-domains`）、新しい IP を差分追加・約3分間見つからない IP を個別削除することで、CDN の短い TTL による IP ローテーションに追従する（チェーン全体のフラッシュは行わないため、更新中に新規接続が失敗する窓は作らない）。
- **`agent-preference.py`**（ホスト専用）— `c3c` の CLI 選択記憶の helper。`key <dir>`（Git common directory またはパスの実体から sha256 のキー）、`read <state-dir> <key>`（strict JSON の検証だけ、書き込みなし）、`write <state-dir> <key> <agent>`（同じディレクトリの一時ファイルから `os.replace` で原子的に保存、0700/0600）。`project-images.py` と同じく `c3c` が固定パスを `python3 -I` で呼び、ビルドコンテキストへは COPY しない。秘密を読まない。終了コードは前述「c3c 入口」節。
- **`validate-build-input.sh`** — `packages.txt`/`requirements.txt` の正規化・照合を担う POSIX sh スクリプト。ビルド時（`Dockerfile.claude` の `RUN`）・起動前診断（`--check`）・テスト（`test-build.sh`）の3者が同じスクリプトを呼ぶことで、検証ロジックが複数箇所へ複製されドリフトする事態を防ぐ（`claude-container#34`）。責務は正規化と照合のみで、インストール・ネットワークアクセスは行わない。
- **`packages.txt`** / **`requirements.txt`** / **`allowed-domains.txt`** / **`node-version.txt`** / **`codex-version.txt`** — claude-container 同梱のデフォルト apt/pip パッケージ・許可ドメイン一覧（空のフォールバック既定値）と、Node.js（`24.18.0`）・Codex CLI（`0.156.0`）の固定版 default。プロジェクト側で上書きする場合は `.c3c/` を使う（「利用側プロジェクトの設定」参照。`node-version.txt`・`codex-version.txt` は空ファイルが opt-out）。`allowed-ports.txt` にはこの種の同梱デフォルトは無く、プロジェクト側に無ければ `c3c` がビルドコンテキスト内に空ファイルをその場で生成する（`init-firewall.sh` 自身が既定値 `443,22` を適用する、という意味。警告は出さない）。

定期 DNS 更新の診断コマンドとログ保持方針は [定期更新の診断とログ](docs/firewall-refresh.md) を参照。

### GitHub meta スナップショット

`init-firewall.sh` の許可リストが使う GitHub IP レンジは `https://api.github.com/meta` から取得する。未認証 GitHub API のレート制限（60 req/h/IP）を避けるため、取得は `c3c` のビルドコンテキスト準備時（`-b` のたび通常1リクエスト、一時エラー時は最大3試行）に1箇所だけで行い、`Dockerfile.claude` がその結果をイメージへ焼き込む。コンテナ起動のたびのライブ取得は行わないため、何度再起動してもレート制限は消費しない。取得に失敗した場合は (1) このプロジェクトの前回ステージング分（`.build-context/<PROJECT_NAME>/` に残っている）、(2) それも無ければ他プロジェクトの最新スナップショット（GitHub の IP レンジは変更頻度が低いため実用上問題ない）を警告付きで再利用し、いずれも無い場合のみビルドを中断する。

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

プロジェクトの移動・削除後に残るイメージは、前述の「欠落パスのイメージ清掃」で診断・限定清掃できる。

`Dockerfile.claude` を編集して `./c3c claude -b /path/to/project` でリビルドする。`-b` を付けると GitHub meta スナップショットの再取得（上記）が試みられ、あわせて `CACHEBUST` にその時点のエポック秒が渡されて install レイヤーのキャッシュが必ず破棄される。これにより、`-b` のたびに `install.sh` が再実行されて最新版の Claude Code が取得される（apt パッケージ等の上位レイヤーはキャッシュを流用するため高速）。再現性が必要な場合は `CLAUDE_CODE_VERSION=1.2.3 ./c3c claude -b /path/to/project` のようにシェル環境で固定する（`.c3c/env` は許可リスト外のため無視される。理由は [`#62`](https://github.com/jj1xgo/claude-container/issues/62)）。

`.c3c/` のパッケージ一覧・許可ドメイン（`allowed-domains.txt`）・許可ポート（`allowed-ports.txt`）・Node バージョン指定（`node-version.txt`）・Codex バージョン指定（`codex-version.txt`）・ベースイメージ指定（`base-image.txt`）を変更した場合も、イメージへ反映するには `-b` での再ビルドが必要。claude-container 側の同梱 default（`node-version.txt`・`codex-version.txt`）が変わった場合も同様で、既存イメージには境界アセットのドリフト診断（起動時の `WARNING` と `--check`）が再ビルドを案内する（旧イメージを自動では削除しない）。`entrypoint.sh`・`init-firewall.sh`・`ipv6-firewall.py`・`firewall-refresh.py`・`codex-mcp-audit.py`・`git-askpass.sh`・`validate-build-input.sh`・`Dockerfile.claude` 自体などビルドコンテキストへステージされるスクリプトの変更も同様（前述「アーキテクチャ」節参照）。

`.build-context/` は claude-container リポジトリ直下に生成されるビルドコンテキストの生成物（`.gitignore` 対象）で、プロジェクトごとに `.build-context/<PROJECT_NAME>/` のサブディレクトリへ分離される。`./c3c --clean /path/to/project` でそのプロジェクト分のみ、`./c3c --clean`（引数なし）で全プロジェクト分をまとめて削除できる。

Claude Code の自動アップデートは `compose.yml` の `DISABLE_AUTOUPDATER: "1"` で無効化している。コンテナは `--rm` で起動するためアップデートを取得しても終了時に消えるためで、バージョン更新は `-b` でのリビルドで行う。

## コンテナ間の永続化

コンテナは `--rm` で起動するため終了時に内部の状態は消えるが、以下の常時マウントはホストに bind mount されているため**コンテナを再起動しても保持される**（`EXTRA_MOUNT`/`SHARED_MOUNT`/`SECRETS_DIR` 等の opt-in マウントは、設定した本人がホスト側に同じパスを維持する限り同様に保持されるが、任意設定のためここには含めない — 一覧は「環境変数」節参照）。

| コンテナ内パス | ホスト側 | 内容 |
|---|---|---|
| `/home/node/.claude/` | `~/.claude/` | Claude のメモリ・設定・セッション履歴 |
| `/home/node/.claude.json` | `~/.claude.json` | Claude の認証情報 |
| `/workspace/` | 起動時に指定したディレクトリ | 作業対象プロジェクト |

## 何ができて何ができないか（git / gh / PAT / hook 早見表）

コンテナ内の `git` と `gh` CLI は認証の渡し方が異なる。`SECRETS_DIR/GITHUB_MAIN_PAT` を配置すると、github.com への HTTPS リモートに対する `git` の認証は `GIT_ASKPASS` 経由で配線される。一方、`gh` は既定で未認証（`GH_TOKEN` 等の ambient export を持たない）であり、同じ PAT を使う場合も「PAT を gh CLI に明示的に渡す」の手順が必要になる。PAT 配置後の `git push` 失敗も、まず接続先と起動中のコンテナへの配線を確認し、その上で PAT の有効期限・対象リポジトリ・権限やブランチ保護等の制約を切り分ける。

**操作系統別の認証経路と可否**

| 操作 | 認証経路 | コンテナ内での可否 |
|---|---|---|
| git ローカル操作（`commit` / `log` / `diff` / `branch` / `merge` 等） | 認証不要（`commit` のみ `GITCONFIG_FILE` で `user.name`/`user.email` が必要。前述） | 可 |
| git リモート操作（`push` / `pull` / `fetch`） | `SECRETS_DIR/GITHUB_MAIN_PAT` 設定時の `GIT_ASKPASS`（credential helper はリセットする） | 既定では **push は不可**。**public リポジトリの fetch/pull は認証不要のため可**（private リポジトリの fetch/pull は不可）。`SECRETS_DIR/GITHUB_MAIN_PAT`（前述）を設定した場合のみ、対象リポジトリへの push（および同トークンでの private リポジトリの fetch/pull）が可能になる |
| `gh` CLI（素） | 認証なし | **既定で未認証・失敗する**（v4〜の正常な既定状態） |
| `gh` CLI（直下の PAT 明示読み） | 「PAT を gh CLI に明示的に渡す」の手順（メイン PAT または `GITHUB_ISSUES_PAT`） | 渡した PAT のパーミッション・対象リポジトリの範囲内で可 |
| `gh` CLI（export 済みの MCP／issues 用 PAT） | `[ -n "${GITHUB_MCP_PAT:-}" ] && GH_TOKEN="$GITHUB_MCP_PAT" gh ...`（空・未設定なら実行しない） | MCP／issues 用 PAT のパーミッション範囲内で可（通常 Issues のみ） |
| MCP（GitHub 公式サーバー） | `${GITHUB_MCP_PAT}`（`.mcp.json` の Authorization ヘッダ、export 経由） | 同上 |

**GitHub 操作が失敗したときの切り分け**

1. 失敗した操作・対象リポジトリ・ツール名・HTTP ステータスを確認する。`git`、PAT を明示した `gh`、プロジェクトの GitHub MCP、エージェントの GitHub 連携（App／Connector）は分けて扱う。連携側の認証が c3c に配置した PAT を使うとは仮定しない。連携の `403 Resource not accessible by integration` や素の `gh` の未認証だけで、配置した PAT の権限不足やコンテナ全体での操作不可とは判断しない。エラー文だけから連携の認証主体・トークン種別を確定しない。
2. `git` の失敗なら、接続先が github.com の HTTPS リモートか確認する（SSH や他ホストは ASKPASS の対象外）。起動中のコンテナで `GIT_ASKPASS` と `GITHUB_MAIN_PAT_FILE` の設定、後者が指すファイルの存在・読み取り可否を、値を表示せず確認する。未配線なら「git push を使う場合」に戻り、`SECRETS_DIR`、PAT 配置後の再起動、ASKPASS 配線に対応したイメージかを確認する。古い実装のイメージには再ビルドが必要だが、PAT の更新だけなら不要。
3. PAT の経路を確認する場合は、前述の明示読み手順で、目的に合った PAT を必要な `gh` コマンドにだけ渡す。明示読み手順の最後のコマンドを `GH_TOKEN="$github_pat" gh api --hostname github.com user --jq .login` に置き換えて認証、対象リポジトリの GET で読み取りを確認する。読み取り成功は書き込み権限の証明ではない。特に public リポジトリの GET やリポジトリ応答の `permissions` は、PAT の対象範囲・書き込み権限を証明しない。詳細は「設定済みスコープの確認」を参照。トークン値や環境変数全体を出力しない。
4. GitHub の PAT 設定画面で対象リポジトリと操作に必要な権限を照合する。[PR 作成](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request)には `Pull requests: write`、[PR マージ](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request)には `Contents: write` が必要。実際の操作にはリポジトリのルールや利用側の承認条件も適用される。Issues 用 PAT の権限拡大やメイン PAT への自動切替は行わず、権限確認だけを目的とする PR 作成・マージもしない。

**メイン PAT / MCP・issues 用 PAT 対応表**

| 項目 | メイン PAT | MCP／issues 用 PAT |
|---|---|---|
| 想定用途 | push・PR レビュー・Release 作成等、主対象リポジトリへの広い操作 | issue 連絡・MCP 経由の操作（クロスリポジトリ含む） |
| 配置・export | `SECRETS_DIR` 直下。値は export されず、パスのみ `GITHUB_MAIN_PAT_FILE` として export | gh の明示読みだけなら直下（非 export）。環境変数を必要とする MCP・hook 等がある場合だけ `export/`（値ごと export） |
| 一般的に許可してよいパーミッション | 用途に応じて `Issues`/`Pull requests`/`Contents` を組み合わせる（`Contents: write` を含めると push・PR承認・マージが明示読みで可能になる点を理解した上で） | `Issues: Read and write` のみ |
| 持たせるべきでないパーミッション | 用途に不要な権限（非 export でも直接読み取りは可能） | `Pull requests: write`・`Contents: write`（MCP のツール面に push・マージ等が現れ、スコープを絞らないと実効化するため） |
| 設定手順・スコープ確認 | 「GitHub トークンの配線」節参照 | 同左 |

**ホストの Claude Code 設定（`~/.claude`）の読み書き**

| 対象 | コンテナ内での可否 |
|---|---|
| user scope の設定 12 項目: `hooks/` `skills/` `plugins/` `commands/` `agents/` `workflows/` `rules/` `output-styles/` `.git/` `settings.json` `CLAUDE.md` `statusline.sh` | 読める・**書けない**（`:ro` 重ねマウント。作成・更新・削除・`/plugin` の install/update・これらへ保存される設定変更はホスト側で行う。ホスト側で更新した内容はコンテナ再起動で反映される）。**plugin について**: plugin のメタデータ（`plugins/known_marketplaces.json`・`installed_plugins.json`）はホストの絶対パスを記録しているため、`c3c` がホストの `~/.claude/plugins` をホストと同じ絶対パスにも `:ro` で重ねて解決する（`compose.plugins-alias.yml`、[`#98`](https://github.com/jj1xgo/claude-container/issues/98)）。対応範囲は `CLAUDE_CONFIG_DIR`（既定 `~`）がホストの `$HOME` と一致するかその配下にある場合で、それ以外（別基点の指定、ホストの `$HOME` がコンテナ内の `/workspace`・`/data`・`/shared`・`/home/node` の配下にある場合）は起動時に `WARNING` を出し、plugin はコンテナ内で読み込めない（起動は止めない）。例外として、ホストの綴りがコンテナ内の `/home/node/.claude/plugins` と一致する場合は既存の `:ro` マウントで解決するため、別名は付けず `WARNING` も出さない。v8.2.0（`:ro` 化）から本修正までの版では、`entrypoint.sh` の旧機構（JSON の書き換え）が読み取り専用で失敗し、メタデータがコンテナ内で解決できないホストの絶対パスを指す場合（通常のホストはこれに当たる）は `cache-miss` になっていた |
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

Claude は `--permission-mode auto`（Claude Code の auto mode）で起動する。auto が利用できないセッション（unsupported model、settings の `disableAutoMode`、サーバー側で無効等）では Claude Code 本体が Manual に戻る（[公式 permission modes](https://code.claude.com/docs/en/permission-modes)、2026-09-21 確認）。auto / Manual の判定は Claude Code 本体の機能であり、claude-container はそれを境界に数えない。ガードレールはコンテナ境界 — マウントされたワークスペースと `/data`・`/shared` への読み書きアクセスを持つ。意図したプロジェクトスコープ外の機密データを含むディレクトリはマウントしないこと。`SHARED_MOUNT`（`/shared`）は同じホストパスを設定した全プロジェクトのコンテナが完全な rw アクセスを持つ共有領域のため、相互に信頼できるプロジェクト間でのみ設定すること。既存のイメージは `-b` で再ビルドするまで旧 entrypoint（従来の既定 `--dangerously-skip-permissions`）のまま動く。起動時と `--check` の境界アセットのドリフト `WARNING` が再ビルドの合図になる（fail-open のため起動は止めない）。`CLAUDE_CODE_VERSION` で `--permission-mode auto` を受理しない版を固定している場合は起動が失敗し、旧フラグへは戻らない。

ネットワークは既定で `init-firewall.sh` によるエグレス許可リストで制限される。Claude Code に必要なエンドポイント（Anthropic API・GitHub 等）と `.c3c/allowed-domains.txt` で指定したドメイン以外への外向き通信は遮断されるため、悪意ある pip パッケージやプロンプトインジェクションが認証情報（`~/.claude.json`）やソースコードを任意の外部ホストへ送信することを防ぐ。開放が必要な場合は `.c3c/env` に `CLAUDE_CONTAINER_NO_FIREWALL=1` を書いて無効化できる（自己責任）。

このガードレールが機能するのは、Claude（およびその子プロセス）がこの許可リスト自体を書き換えられないことが前提になる。`Dockerfile.claude` の `ENTRYPOINT`（前述「アーキテクチャ」節参照）でコンテナ起動時に関連 capability（`NET_ADMIN`/`NET_RAW`）を剥奪しており、iptables の実消費者は `sudo` 経由で root になった `init-firewall.sh` のみに限定される。file capabilities 付きバイナリの追加導入や `podman exec` 経由には限界が残る（[詳細](SECURITY-CLAIMS.md#c-1)）。

**制限しても残るリスク**: DNS クエリを使ったトンネリング、許可済みサービス（GitHub 等）自体への送信、CDN の共有 IP 経由の到達は原理上防げない。`/etc/resolv.conf` から IPv4 リゾルバを検出できない場合（通常の Podman 環境では稀）、DNS（53番ポート）は宛先無制限で許可される縮退動作になる（起動時に `WARNING: /etc/resolv.conf に IPv4 リゾルバがないため、DNS を任意のホストへ許可します` が出力される）。許可ドメインの IP は約15秒間隔のバックグラウンド再解決で追従するが（上記アーキテクチャ節参照）、ローテーション直後からリフレッシュが反映されるまでの数十秒間は新規接続が失敗しうる（コンテナ再起動が必要だった以前と比べれば大幅に縮小されるが、ゼロにはできない）。GitHub IP レンジはビルド時スナップショット固定のため、コンテナ再起動では更新されず `-b` でのリビルドが必要。ビルド時（`pip3 install` 等）のネットワークは制限されない。

**`packages.txt`/`requirements.txt` のビルド時インジェクション対策にも残余がある**: 両ファイルは `validate-build-input.sh` による allowlist 検証を経る（前述「利用側プロジェクトの設定」「アーキテクチャ」節）が、PyPI は open publishing のため、`requirements.txt` の名前指定だけで任意パッケージの sdist に含まれる `setup.py` がビルド時 root で実行される経路が原理的に残る（`claude-container#34`）。apt 側は設定済みリポジトリ内のパッケージに限られるため同じ経路は無い。

**claude-in-chrome 連携はファイアウォールでは原理的に遮断できない**（`jj1xgo/claude-container#32`）: `.mcp.json` を介さないネイティブ機能のため MCP 監査ゲートの対象外で、コンテナ内から到達・実行可能である。ホスト側の通知は事前承認ではなく事後通知＋任意キャンセル（fail-open）で、コンテナ内のコードが人間の事前承認なしにホストの実ブラウザを操作しうる——「ガードレールはコンテナ境界」という前提の外側にある残存リスク（[詳細](SECURITY-CLAIMS.md#c-2)）。

**MCP サーバーの承認プロンプトを壁に数えない**: Claude Code 本来の仕様では project-scoped の `.mcp.json` サーバー利用前に承認プロンプトが表示されるが、従来の既定 `--dangerously-skip-permissions` 下ではこの確認が実行されないことを実機で確認済み（承認記録 `enabledMcpjsonServers` が空のままサーバーが稼働する）。現在の既定 `--permission-mode auto` 下の挙動は未計測で、いずれにせよ承認系の設定（`enabledMcpjsonServers` 等）はコンテナ内から書き換え可能なため壁にならない。stdio タイプ（コンテナ内でコマンドを実行するサーバー）は、この確認が無いままセッション開始と同時に人間・モデルどちらの判断も挟まず実行され、コンテナ内のトークン類を読めてしまうため、claude-container 側で `entrypoint.sh` による対話確認ゲートを設けている（前述「MCP サーバーの追加」節）。http／sse タイプはこのゲートの対象外だが、接続先はファイアウォールの許可リストが審査する。**残存する経路**: `claude mcp add` によるローカル／ユーザースコープの登録（`~/.claude.json` 側）はこのゲートの対象外で、既に侵害されたセッションによる永続化の手段になりうる。

**`.c3c/env` は信頼できないリポジトリでは攻撃面になる**: `env` で受け付けるキー（前述「環境変数」節の表）には `CLAUDE_CONTAINER_NO_FIREWALL=1` のようなセキュリティ機構の opt-out 変数や、マウント先を決めるキーが含まれるため、そのプロジェクト自身の `.c3c/env` に書かれていれば有効になってしまう。信頼できないリポジトリを起動する前に `.c3c/env` の中身を確認すること。

**Claude 経路で `.mcp.json` に追加ゲートを設ける理由は、入力の信頼度でなく帰結の重大性で線を引いているため**（`claude-container#29`）: リポジトリ同梱の設定（`.c3c/env` と `.mcp.json` の両方）は、いずれも起動前に運用者がレビューする責任範囲にある——同じリポジトリに同梱される以上、どちらか一方だけを「信頼できる」「信頼できない」と区別する根拠は無い。claude-container が追加の対話ゲートを設けるのは、レビューを怠った場合の帰結が「セッション開始と同時の任意コード実行」になる場合に限る（＝ `.mcp.json` の stdio 型）。`env` で受け付けるキーは許可リスト（前述「環境変数」節の表）に限られ、`PATH`・`HOME` 等ホスト側の実行や基点に影響するキーは export されない（[`#44`](https://github.com/jj1xgo/claude-container/issues/44)）。対象プロジェクト直下の `.env` も compose の補間に使わない（[`#60`](https://github.com/jj1xgo/claude-container/issues/60)）。別軸として、境界へ影響するキー（`EXTRA_MOUNT`・`SHARED_MOUNT`・`SECRETS_DIR`・`GITCONFIG_FILE`・`CODEX_DIR` 等）の使用は起動時に一覧して気づけるようにしている（`guard_env_boundary_keys()`）。この可視化は fail-closed ではない——`env` は運用者自身が書く設定という前提は変えていないため。

起動時の可視化を実際に確認したい場合は `.c3c/env` に `CLAUDE_CONTAINER_NO_FIREWALL=1`（または `EXTRA_MOUNT`/`SHARED_MOUNT`/`SHARED_MOUNT_HOME_ALIAS`/`AGENTS_DIR`/`SECRETS_DIR`/`GITCONFIG_FILE`/`CODEX_DIR`/`CLAUDE_CONFIG_DIR`）を書いて起動する。値そのものはログに出さず、キー名のみを一覧する。

**ホストの Claude Code 設定の読み取り専用保護**: ホストの `~/.claude`（`CLAUDE_CONFIG_DIR` 基点）はコンテナへ rw で bind mount される（認証情報・transcript の共有に必要）が、そのうちホスト側で実行・読込される user scope の設定 12 項目（前述「何ができて何ができないか」節の表。`.git/` を含む）は、`compose.yml` が rw マウントの内側に `:ro` の bind mount を重ねることで、**この mount 経由では**コンテナ内から書き換えられない。侵害されたセッションがここへ hook・skill・plugin 等を書くと、ホストの Claude Code がそれを読み込み・実行する（user settings の hooks は file watcher で稼働中セッションにも反映される）ため。マウント先がホストに無いと podman がサブ uid 所有の実体を作って残骸になるので、`c3c` が起動直前（全ガードと MCP 承認の後）に欠けている項目をユーザー権限で空のまま作り、その旨を `INFO:` で表示する（`--check` は作らず `[WARN]` で報告する）。12 項目のいずれかが symlink または型の違う実体（ディレクトリ予定位置にファイル等）だと起動を中止する。この型と symlink の検査は、通常起動では欠けている項目を 1 つも作らないうちに 12 項目すべてについて行うので、不正な項目があれば何も作らずに停止する（作成途中の I/O エラーや並行した置き換えまでは巻き戻さない）。symlink を拒否するのは、`:ro` の子マウントはリンク先に付く一方でリンク自体は rw の親マウント内に残り、コンテナ内で削除して作り直せば書き込み可能な実体に置き換えられる（保護の迂回）ため。**限界**: (1) 保護はこの mount 経由に限る。`/workspace`（作業ディレクトリ）・`EXTRA_MOUNT`・`SHARED_MOUNT` が `~/.claude` を含む、または保護対象そのものを指す場合は別経路から書けるため、起動時に `WARNING` を出す（検出はパスの包含関係のみで、別マウント内部のリンク等は検出しない）。(2) project scope の設定（`/workspace/.claude/` 配下と `.mcp.json`）は対象外で、ホストでそのフォルダを trust 済みならホストの Claude Code がそれらを読み込む。(3) `~/.claude.json`（trust フラグ・user scope の MCP 登録）、auto memory（`projects/<p>/memory/`）、`agent-memory/`、`shell-snapshots/`、`session-env/` は対象外（Claude Code が実行時に書くため）。前 3 者はホスト側セッションへの指示の再注入経路になりうる。(4) 保護された参照元（`settings.json`・`CLAUDE.md` の import・hook や plugin が読む依存ファイル）が `~/.claude` の外や対象外領域を指していれば、その先は保護されない。(5) `.c3c/env` の `HOME`・`PATH` 等でホスト側の実行や基点をずらす経路は、受け付けるキーを許可リストに限定したことで閉じた（`#44`）。許可キーのうち `CLAUDE_CONFIG_DIR` は基点そのものを指定するキーなので、`guard_env_boundary_keys()` の一覧表示の対象にしている。(6) ホスト側で 12 項目のファイルを rename で置換した場合、稼働中のコンテナは旧実体を見続ける（再起動で反映）。(7) plugin の別名マウント（`compose.plugins-alias.yml`、[`#98`](https://github.com/jj1xgo/claude-container/issues/98)）は `plugins/` と同じ source を同じ `:ro` でホストと同じ絶対パスにも重ねるもので、保護対象を増やしも減らしもしない。destination はホストの `$HOME` 配下の綴りに限り、コンテナ内の固定マウント先（`/workspace`・`/data`・`/shared`・`/home/node`）と一致または配下になる場合は付けない（対象プロジェクトや他マウントの内容を隠さないため。判定の正本は `c3c` の `plugins_alias_target()`）。destination の親ディレクトリ（例 `/home/<host user>`）は podman がコンテナ作成時に root 所有で作るため、コンテナ内の非特権プロセスからは書けない。(8) `.git/` は `~/.claude` 自体を git リポジトリにしているホスト向け（[`#129`](https://github.com/jj1xgo/claude-container/issues/129)）。`.git/hooks/` と `.git/config`（`core.hooksPath` 等）はホストで `git -C ~/.claude` を打った時点でホスト権限で実行・参照されるため、hook と同じ扱いにする。リポジトリでないホストでも空ディレクトリで作って重ねる（空の `.git` は git に無視され、後から `git init` すれば通常どおり初期化される。コンテナが `.git` を植え付けて後日の `git init` で有効化される経路を閉じるため）。`~/.claude` を別リポジトリの worktree や submodule にしていて `.git` がファイル（gitfile）の構成は、型検査により起動を中止する（実ディレクトリの `.git` に置き換える）。コンテナ内からは `git -C ~/.claude log`・`status` は読めるが、commit・config 変更はホストで行う。`.git/config` の `core.hooksPath`・`include.path` が `~/.claude` 内の 12 項目以外（例: 追跡している `.githooks/`）や `~/.claude` の外を指す構成では、その先は限界 (4) のとおり保護されない。hooks は既定の `.git/hooks/` に置くこと。`~/.claude` が git リポジトリでないホストでは別の限界が残る: 空の `.git` は無効なので、コンテナが rw の `~/.claude` 直下に `HEAD`・`objects/`・`refs/`・`config` を置くと、git は `~/.claude` 自体を bare リポジトリとして扱い（`safe.bareRepository` の既定 `all`）、ホストで `git -C ~/.claude` を打った時点でその `config`（`core.pager`・`core.sshCommand`・`core.fsmonitor` 等）を読む（git 2.53.0 で再現）。`hooks/` は `:ro` なので bare 側の hooks は植え付けられない。緩和策はホストで `git config --global safe.bareRepository explicit` を設定すること（自動探索で見つかった bare リポジトリを拒否する）。`~/.claude` を実際に repo にしているホストでは有効な `.git` が先に使われるためこの経路は無い。

`SECRETS_DIR`（前述「GitHub トークンの配線」節）を設定した場合、上記「許可済みサービス自体への送信」というリスクが受動的なものから能動的なものに変わる: プロンプトインジェクションや悪意あるパッケージがコンテナ内からトークンを読み取り（直下の PAT はファイルとして、`export/` 配下の PAT は環境変数としても）、そのスコープ内で GitHub 等に書き込める。緩和策は各 fine-grained PAT のスコープ最小化（対象リポジトリ限定・短期限）で、被害を該当リポジトリでの操作に構造的に限定すること。利用者は export するトークンを実際に環境変数を必要とする用途に絞り、権限も最小にする。実装は権限を検査しないため、Issues 限定等の制限は GitHub 側で設定・確認する（「GitHub トークンの配線」節の設計原則参照）。`SECRETS_DIR` は汎用機構であるため、この能動的リスクは GitHub トークンに限らず持ち込んだ全シークレットに及ぶ（1コンテナに持ち込むのは実際に使う最小本数に留めること — 前述）。

`CODEX_DIR`（前述「Codex CLI をセカンドオピニオンとして使う」節）を設定した場合、コンテナ内のコードは Codex の認証情報（`auth.json`、ChatGPT アカウントのアクセストークン）を読める。`SECRETS_DIR` と異なり rw マウントのため、コンテナ側から書き込みも可能 — 専用ディレクトリ（実 `~/.codex` でない）を指定する設計により、汚染がホスト側の Codex 実行環境（`config.toml` の `notify` フック等）へ波及する経路を遮断している。Codex は `codex exec` としてセッション中に Claude が判断して実行する通常のコマンドであり、`.mcp.json` には登録しないため、前述の MCP 監査ゲート（TOFU）の対象外である。同ゲートが対象とするのは「セッション開始と同時に人間・モデルどちらの判断も挟まず実行される」経路であり、`codex exec` はそれに当たらない。

`SECRETS_DIR/GITHUB_MAIN_PAT`（前述「git push を使う場合」）に `Contents: write` を付与した場合、能動的リスクは push・PRマージにも及ぶ: プロンプトインジェクションや悪意あるパッケージが、明示読み（前述の gh CLI への明示読み手順等）を介して対象リポジトリへの意図しないコミット・push・マージを引き起こしうる。非 export であることは「黙ってはできない」という一手間の壁ではあるが、コンテナ内の任意のプロセスがそのファイルパスを読める以上、確実な壁ではない。緩和策は他のトークン同様スコープ最小化（対象リポジトリ限定）に加え、GitHub 側の branch protection（force-push 禁止・レビュー必須化）を組み合わせること。

自リポジトリ向けのメイン PAT に `Pull requests: Read and write` を付与した場合の追加リスク:

- **攻撃対象面の拡大**: 他者PRのタイトル・本文改変、レビュー依頼スパム、妨害目的のクローズが可能になる。Issue操作と同種だが一段重い
- **`Contents: write` を付与しない限りpush・PRマージには至らない**: PRマージ（`PUT …/pulls/{n}/merge`）に必要な権限は `Contents: write` であり、`Pull requests` 権限だけでは実行できない。ただしメイン PAT に `Contents: write` も付与している場合は、この境界は無い（push 節参照）
- **auto-merge 経由の境界迂回に注意**: PRレビュー承認（`gh pr review --approve`）は `Contents: write` なしで実行できる。対象リポジトリで auto-merge が有効な状態だと、コンテナ内トークンによる承認だけで required review 条件が満たされ GitHub 側が自動マージしてしまう可能性がある。auto-merge を無効に保つこと（1枚目の壁）に加え、同梱の PreToolUse hook（`examples/hooks/block-pr-approve.sh`、配線すれば）が承認操作の自律実行を機構的にブロックできる（2枚目の壁 — 適用範囲と限界は「何ができて何ができないか」節参照）。MCP 経由の承認（`mcp__github__pull_request_review_write` 等）はこの hook の検査対象外のため、MCP へは「GitHub トークンの配線」節の `permissions.deny` を別途の壁として使うこと

## Podman 固有の注意

- Codex で `bwrap: Can't mount proc on /proc: Operation not permitted` が出る場合は、[#140 の調査・診断手順](docs/codex-proc-investigation.md)を参照する。報告環境（Podman 5.8.6）では Codex 0.155.1 とシステム版 bubblewrap 0.12.0 の組合せで失敗し、システム版を外して Codex 同梱版を使う比較では成功した。#145 以降の c3c は、システム版が残っていても Codex 経路で同梱版を優先する（前述「Codex CLI を対話で使う」節の sandbox の bubblewrap）。依存パッケージを削除する必要はなく、旧イメージは `-b` で再ビルドする。`unmask=/proc/*` の既定追加は行わない。

- `userns_mode: keep-id` はホストユーザーの UID/GID をコンテナ内にマップする Podman 固有の機能。Docker に移植する場合は削除する。
- `--in-pod false` は Podman Compose がデフォルトでサービスを Pod にラップする挙動を抑制する。Docker Compose はこのフラグを無視する。

## 変更後の確認

claude-container 自体を開発する場合は [AGENTS.md](AGENTS.md) と [docs/development-invariants.md](docs/development-invariants.md) を参照する。

通信の回帰テストはローカル HTTP サーバーと実 curl を使う。
Ctrl-C の確認には util-linux の `script` で疑似端末を用意する。

テストは `lint.sh`、`test-build.sh`（ベクタ表・契約テスト・ランチャーテスト・実イメージのビルドと起動確認）、`examples/hooks/tests/test-block-pr-approve.sh`（同梱 hook の回帰テスト）で行う。スクリプトや Compose / Dockerfile を編集した後は以下で確認する。

GitHub Actions（`.github/workflows/ci.yml`）が、PR と `main` への push のたびに `lint.sh`（Compose 検証を含む）、`./test-build.sh --validator-only`、`./test-build.sh --launcher-only`、`bash examples/hooks/tests/test-block-pr-approve.sh` を `ubuntu-24.04` の runner で実行する。`test-build.sh` は検査の詳細を `.claude/test-results/` のログにしか書かないので、CI はどれかが失敗したときだけそのログを Actions に出す。Compose 検証は runner 同梱の Docker Compose を `PODMAN_COMPOSE_PROVIDER` で指定し、Podman 経由で実行する。Podman と provider が無ければ CI は失敗し、使用した版をログに残す。shellcheck はホストの開発環境と同じ版を SHA256 固定で取得する。実コンテナ検証は独立した手動・定期 workflow（`.github/workflows/runtime.yml`）で行う。`test-build.sh --build-only` と `--config-ro-only` を再利用し、起動後の権限・IPv4 の許可／禁止通信も確認する。PR の必須チェックは増やさない。実行方法・runner の前提・`not run` の扱いは [実コンテナの手動・定期検証](docs/runtime-ci.md) を参照。追加パッケージ・不正入力のビルド検査を含む `./test-build.sh` の全体実行は引き続きホストで行う。fork からの PR は GitHub の設定により初回の実行が承認待ちになることがあり、その間は赤でも緑でもない。

```bash
./lint.sh
```

`lint.sh` は、リポジトリ内の bash スクリプト（gitignore 対象を除く追跡済み・未追跡ファイルから shebang で自動判定するため、スクリプトを追加・削除しても対象リストの更新は不要）への `bash -n` と `shellcheck`、および `podman compose -f compose.yml config` をまとめて実行する。shellcheck 未インストール時はエラーで失敗する（`sudo apt-get install shellcheck` で導入）。podman が無い環境（コンテナ内での開発時）では Compose 検証のみ警告付きでスキップされる。`LINT_SKIP_COMPOSE=1` を与えると、podman の有無に関わらず Compose 検証だけを警告付きでスキップする（Compose を実行できない環境用。CI では指定しない）。実行時に shellcheck の版を表示し、CI（`.github/workflows/ci.yml` の `SHELLCHECK_VERSION`）の固定版と違えば WARNING を出す（判定は変えない。版差で指摘の有無が変わることがあるため、NG の原因の切り分け用）。コンテナ内の開発イメージは Debian パッケージの shellcheck を使うため CI と版が違うことがあり、この WARNING は想定内。`LC_ALL`・`LC_CTYPE`・`LANG` がすべて未設定のときは `LC_CTYPE=C.UTF-8` を補い、日本語を含む行で shellcheck の出力が途中で切れないようにする（`LC_ALL` は他カテゴリも上書きしてしまうため使わず、利用者が個別に `LC_CTYPE` を設定している場合はそれを優先する）。

`compose.yml` の `:ro` 重ねマウント、または `c3c` の `prepare_claude_config_ro()` を編集した場合は、ビルド済みのテストイメージ `localhost/claude-test`（`./test-build.sh` の全実行で作られる）がある状態で `./test-build.sh --config-ro-only` を実行する。実物の `compose.yml` とイメージで 12 項目への書き込みが拒否されること、実物のランチャーが placeholder 作成・型検査・`--check` の無書き込み・compose への `CLAUDE_CONFIG_DIR` 受け渡しを正しく行うことを、それぞれ別のテストで確認する（両者を通した対話起動は手動で行う）。

`c3c` のガード関数（`guard_*`・`prepare_claude_config_ro()`）を編集した場合は `./test-build.sh --launcher-only` を実行する。podman をダミーに置き換えた隔離環境（一時 `HOME`・空の環境変数）で実物のランチャーを起動し、各ガードの通常起動と `--check` の挙動、compose へ渡る環境変数を検証する。実 podman が不要なので、コンテナ内の開発セッションや CI からも回せる。通常の `./test-build.sh` にも含まれる。

`c3c` 入口（旧名 symlink の同一契約・parser・`resolve_launcher_path()`・`select_c3c_agent()`・`prompt_c3c_agent()`・`write_agent_preference()`・`run_main_compose()` 以降の終了コード保持）と `agent-preference.py` の変更も `--launcher-only` に含む。単独では `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_agent_preference.py' -v` と `... -p 'test_c3c_launch.py' -v` を使う（後者は通常ファイルの `c3c` と外部 symlink を fake Podman・専用 PTY で起動し、初回選択・EOF・Ctrl-C・非 TTY、記憶の更新時点、`--check`/`--clean` の無書込、旧名 symlink 経由の記憶更新、symlink 解決を検証する。ハングはタイムアウトで失敗になる）。`tests/test_codex_launch.py` も `c3c` を起動し、Claude 固定が目的の通常起動では `claude` を明示する。実 Podman と実認証での対話受入は fake Podman の成功で代替しない。

設定ディレクトリの選択（`select_project_conf_dir()`、`PROJECT_CONF_DIR` を使う resolver・staging・hash・案内文）の変更も `--launcher-only` に含む。単独では `... -p 'test_c3c_config.py' -v` を使う（新名・旧名・なし・二重配置・ファイル/dangling/symlink の各配置を `c3c` 直接・旧名 symlink 経由・`--check` で検証し、`--check` の継続と無書込、`--clean` の独立、新旧配置での staged file と asset hash の一致、固定アセットの上書き不可、案内先の一貫性を含む）。旧設定名 `.claude-container.d/` の fixture は互換読込の検査として残す。旧コマンド名の検査は外部 symlink から `c3c` を呼び出す形にし、通常起動・コピー・関数抽出の参照先は `c3c` に移行している。実移行（backup → 改名 → `--check` → 起動 → 戻し）は fake Podman では代替せず、実 Podman で確認する。

Node/Codex の既定ビルド入力（同梱 `node-version.txt`・`codex-version.txt`、`resolve_asset_source()` の overridable 解決、`guard_build_input_defaults()`、`guard_codex_agent()` の opt-out 案内）の変更も `--launcher-only` に含む（`tests/test_c3c_config.py` の `BuildInputDefaultTests`: 新旧配置それぞれで欠落→同梱 default・project pin 優先・空ファイル opt-out、pin＝default と欠落の hash 同一、空 opt-out の Codex 起動拒否、Node 空＋Codex 有効の `WARNING` と `--check` の WARN）。実ビルドは `./test-build.sh`（全体）で行う: `--build-only` 経路がイメージ内の `node --version`・`npm --version`・`codex --version`・`claude --version` と `codex-mcp-audit.py` の起動を検査し、Node/Codex は同梱ファイルの固定値との一致を必須にする。全体実行はさらに、空の `codex-version.txt` で Codex が入らないこと、空の `node-version.txt`＋Codex 有効＋npm の無いベースでビルドが `npm が必要` のエラーで止まること、プロジェクト側の pin（Node 22.14.0）が default より優先されることを実ビルドで確認する。同梱 default を変えたときは `-b` の再ビルドと両 CLI の起動、旧イメージに対する `--check` のドリフト診断を実 Podman で確認する。

`project-images.py` と `--clean-missing` の変更も `--launcher-only` に含む。単独では `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_project_images.py` を使う。参照保護・親保持と JSON 形式は、利用中のストレージから隔離した Podman でも確認する。ラベルの配線を変えた場合は、明示 build と run の暗黙ビルドへの受け渡し、実ビルドでのラベル値も確認する。

IPv6 の変更時は `./test-build.sh --launcher-only` に含む Python テストと設定テストを実行する。`lint.sh` は通常と IPv6 override の両方の Compose 設定を検証する。実 IPv6 の確認は pasta を使うコンテナで別途行う。

plugin の別名マウント（`compose.plugins-alias.yml`・`plugins_alias_target()`・`guard_plugins_alias()`）の変更時も `./test-build.sh --launcher-only` を実行する（判定関数の単体検査、build・run 各呼び出しへの配線、`--check` の不変を含む）。`lint.sh` は override 単独と IPv6 override との 3 ファイル同時の Compose 設定も検証する。plugin が実際に読み込まれるかは `-b` で起動したコンテナ内の `claude plugin list` で確認する（`entrypoint.sh` にはこの境界のマーカーコメントがあり、`tests/test_ipv6_entrypoint.py` が抽出境界として使う — 文言を変えたらテスト側も同時に変える）。

`entrypoint.sh` の Claude 起動引数（`--permission-mode auto`）を変更した場合は `tests/test_codex_entrypoint.py`（`--launcher-only` に含む）に加え、`-b` の再ビルドと実起動で `podman top <container> pid,args` に引数が出ること（実 argv）、セッション内の表示で permission mode を確認すること（実モード。auto が利用できないセッションでは Manual になる）、再ビルド前の旧イメージに対して起動時と `--check` がドリフトの `WARNING: 境界アセット（entrypoint.sh・init-firewall.sh 等）がイメージのビルド後に変更されています。` を出す（`--check` では結果 `WARN` に集計される）ことを実 Podman で確認する。CLI 選択の記憶により `c3c -b` は Codex を起動しうるため、Claude の確認では `c3c claude` と明示する。

Codex 同梱 bubblewrap の固定リンク（`Dockerfile.claude` の `# >>> c3c codex-bwrap` 区切りの RUN、`entrypoint.sh` の Codex 経路の PATH）を変更した場合は、`tests/test_codex_bwrap.py`（npm の nested/hoisted/legacy・x64/arm64 の解決、欠落・実行不能・target 外・help 4 項目の拒否。Node.js が必要）と `tests/test_codex_entrypoint.py`（全段の PATH 一致・Claude の不変・欠落時の停止）を含む `--launcher-only`、最終イメージの所有者・mode・書込不可を確かめる `--build-only` を実行する。arm64 は fixture の合格であり、実機の合格とは区別する。対応 Codex を更新するときは、上流の [launcher.rs](https://github.com/openai/codex/blob/rust-v0.156.0/codex-rs/linux-sandbox/src/launcher.rs)・[PATH 探索](https://github.com/openai/codex/blob/rust-v0.156.0/codex-rs/sandboxing/src/bwrap.rs)・[npm ラッパー](https://github.com/openai/codex/blob/rust-v0.156.0/codex-cli/bin/codex.js)・[proc fallback](https://github.com/openai/codex/blob/rust-v0.156.0/codex-rs/linux-sandbox/src/linux_run_main.rs) の新版で、PATH 候補の選び方、help の必要オプション、npm の配置、`/newroot/proc` の失敗検出が変わっていないことを確かめる。そのうえで、システム版 bubblewrap のある fixture で通常起動の `pwd`/`git status` と通信・mount の受入をやり直す（[調査記録](docs/codex-proc-investigation.md)の「#145 の受入」）。

`SHARED_MOUNT` の別名マウントと `AGENTS_DIR`（`compose.shared-home.yml`・`compose.shared-host.yml`・`compose.agents.yml`・`guard_shared_home_alias()`・`guard_agents_dir()`）の変更時も `./test-build.sh --launcher-only` を実行する（opt-in の配線、不正値の拒否、`--check` の不変、symlink の実体解決を含む）。このランチャーテストの仮 HOME は `mktemp` 配下に作るため、`TMPDIR` が `/var/tmp` や `/run/user/<uid>` の配下だと予約領域の拒否条件に当たり、正常系も失敗する。該当する環境では `TMPDIR=/tmp ./test-build.sh --launcher-only` として実行する（全体テストも `TMPDIR=/tmp ./test-build.sh`）。`lint.sh` は override 単独と 6 ファイル同時の Compose 設定、`${VAR:?}` の fail-closed を検証する。実際に別名が読めて別名経由で書けないこと、`/shared` が rw のままであることは `-b` で起動したコンテナ内で確認する（前述「ホストの指示ファイルとスキルをコンテナ内で解決する」節）。

`init-firewall.sh` の `resolve_allowed_ports()`・`build_domain_list()`・`refresh_domains()`・`add_or_touch_domain_ip()`・`prune_stale_domain_rules()` を編集した場合も `./test-build.sh --launcher-only` を実行する。ポート検証、許可ドメイン入力検証（`tests/test-allowed-domains.sh`）と DNS 応答の回帰テスト（`tests/test-refresh-domains.sh`）、ルールの更新順序・世代非更新・期限切れ削除の回帰テスト（`tests/test-domain-rule-lifecycle.sh`）を含む。各テストは `bash tests/<ファイル名>.sh` で単独実行できる。実際の iptables と接続の確認は別途コンテナで行う。

`Dockerfile.claude`（`ENTRYPOINT` の `setpriv` ラップ）を編集した場合は `-b` でのリビルドと実機起動が必須（前述「セキュリティモデル」節参照）。コンテナ内セッションから `sudo` 無しの `iptables` 操作ができないことが正しい状態であり、ファイアウォールルール自体の確認は `podman exec --user root <container> iptables -S`（ホスト側から）で行う——セッション内からの `iptables -S` 単体実行は権限剥奪後には失敗するようになる。

## 表記

この repo の文書・スクリプトのメッセージとコメント・tag メッセージ・Release 本文・Issue と PR は**日本語のみ**で書く。v8.2.1 までは README と tag が日英併記だったが、v8.2.1 を最後に英語版を廃止した（既存の tag と Release は書き換えない）。例外として英語のまま残すのは、`ERROR:` / `WARNING:` / `INFO:` / `[OK]` / `[WARN]` / `[FAIL]` の接頭辞（テストと `--check` の集計が照合する機械可読トークン）、`[y/N]`、環境変数名・関数名・コマンド名・URL、`LICENSE` の法文、git や gh が出す文字列と照合する部分。日本語の文中の技術用語（base image、stdio、hash、fail-closed 等）は英語のまま書いてよく、「行にひらがなかカタカナが含まれる」ことを日本語化済みの判定に使う。

## バージョニング

[Semantic Versioning](https://semver.org/lang/ja/) に従い、リリースは annotated git タグ（`vX.Y.Z`）で管理し、タグごとに、タグメッセージを本文にした GitHub Release を作成する（CHANGELOG ファイルは作らない）。`--notes-from-tag` は `-R` と併用できない（gh 2.100.0 で実測）ので、本文はファイル経由で渡す:

```bash
git tag -l --format='%(contents)' vX.Y.Z > /tmp/notes.txt
gh release create vX.Y.Z -R jj1xgo/c3c --verify-tag --title vX.Y.Z --notes-file /tmp/notes.txt
```

番号は利用者から見えるインターフェース（CLI 引数・`.c3c/` の設定形式・デフォルト挙動）を基準に判定する:

- **MAJOR** — 後方互換性が壊れる変更（デフォルト挙動の変更、設定形式の削除・非互換化など、利用者が対応しないと従来どおり動かないもの）
- **MINOR** — 後方互換な機能追加（既存の使い方はそのまま動く）
- **PATCH** — 後方互換なバグ修正のみ

バージョン履歴は GitHub の [Releases ページ](https://github.com/jj1xgo/c3c/releases)で一覧・購読できる（`git tag -n1` でも確認可能）。

## 参考

- [Running Claude Code CLI in a Container (Endpoint Dev Blog)](https://www.endpointdev.com/blog/2026/03/claude-code-cli-in-container/) — フォーク元作者 Seth Jensen によるコンテナ化の解説記事

## ライセンス

GPL-3.0。フォーク元（sethjensen1/claude-container）は MIT ライセンス。詳細は [LICENSE](LICENSE) を参照。
