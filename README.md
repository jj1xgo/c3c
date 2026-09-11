# claude-container

[日本語](#日本語) | [English](#english)

---

<a id="日本語"></a>

## 日本語

[sethjensen1/claude-container](https://github.com/sethjensen1/claude-container) をフォークした Podman 上の Claude Code コンテナ実行環境。

Podman + Compose を使い、ホストの Claude 認証情報を共有しながら任意のディレクトリを `/workspace` にマウントして Claude Code を起動する。

apt/pip パッケージは `.claude-container.d/`（後述）でプロジェクトごとに指定でき、claude-container リポジトリ自体にはプロジェクト固有のパッケージを持たせない。

- [前提](#前提)
- [使い方](#使い方)
- [起動前チェック（--check）](#起動前チェックcheck)
- [環境変数](#環境変数)
- [利用側プロジェクトの設定](#利用側プロジェクトの設定)
- [MCP サーバーの追加](#mcp-サーバーの追加)
- [アーキテクチャ](#アーキテクチャ)
- [イメージの変更](#イメージの変更)
- [コンテナ間の永続化](#コンテナ間の永続化)
- [何ができて何ができないか（git / gh / PAT / hook 早見表）](#何ができて何ができないかgit--gh--pat--hook-早見表)
- [セキュリティモデル](#セキュリティモデル)
- [Podman 固有の注意](#podman-固有の注意)
- [変更後の確認](#変更後の確認)
- [バージョニング](#バージョニング)
- [参考](#参考)
- [ライセンス](#ライセンス)

### 前提

- [Podman](https://podman.io/) および `podman-compose`
- ホストに `~/.claude.json`（Claude 認証情報）が存在すること

### 使い方

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

### 起動前チェック（`--check`）

複数のファミリープロジェクトが本リポジトリを直接参照して稼働している運用（内部運用issue参照）では、破壊的変更（v3.0.0 の旧設定形式削除、v4.0.0 のトークン配線変更等）の後、各プロジェクトの設定を更新しないと起動が fail-closed ガードで停止する。`--check` は起動せずにこれを事前診断し、リビルド・起動前に必要な移行作業を一括提示する。

```bash
# 起動台帳（後述）の全プロジェクトを一括診断
./claude-container --check

# 個別のディレクトリを診断（複数指定可）
./claude-container --check /path/to/project-a /path/to/project-b
```

- **起動台帳**: 通常起動（`--clean`/`--check` を除く）のたびに、対象ディレクトリのホスト絶対パスが `~/.local/state/claude-container/projects` へ自動記録される（手動メンテ不要）。`--check` を引数なしで実行すると、この台帳に記録された全プロジェクトを一括診断する。`--clean <directory>` はそのプロジェクトを台帳からも削除し、`--clean`（引数なし）は台帳自体を削除する。シンボリックリンク経由と実体パスで起動すると別エントリとして記録される点に注意（`compute_project_name()` のプロジェクト識別基準と同じ）。
- **検査項目**: legacy トークン変数（`GH_TOKEN_FILE` 等）・`SHARED_MOUNT`/`GITCONFIG_FILE`/`SECRETS_DIR`/`CODEX_DIR` の存在とレイアウト（`noexport/` 残存等）・パーミッション・`packages.txt`/`requirements.txt`/`allowed-domains.txt` の有無・イメージの既ビルド有無（`podman` 利用可能な場合のみ）・MCP 監査ゲートの承認状態・`packages.txt`/`requirements.txt` の内容診断。**起動時ガードと内容診断は別モードで動く**: 上記の有無チェック等は通常起動時の fail-closed ガードと同一の関数を共有し診断結果と実際の起動挙動が乖離しないが、内容診断（`packages.txt`/`requirements.txt` の allowlist 検証）は `--check` 専用の助言診断で、通常起動時の強制点（`Dockerfile.claude` の `RUN`）とは別に呼ばれる。ただし両者は同じ `validate-build-input.sh` を呼ぶため、判定ロジック自体が乖離することはない。
- **非対話・対象リポジトリは不変**: `--check` は TTY 確認を一切行わない（MCP stdio 型サーバーが未承認の場合は「初回起動時に確認プロンプトが出ます」と報告するのみ）。台帳に記録があるが実体が見つからないプロジェクトも FAIL として報告するだけで、台帳を黙って書き換えない。**保証の範囲は「対象リポジトリと `.build-context/` を変更しない」こと**（内容診断は `mktemp` 経由で `/tmp` 配下に作業ファイルを必ず作るため、無限定の「書き込みゼロ」ではない）。
- **終了コード**: 診断対象のいずれかが FAIL の場合は非0、それ以外は0で終了する。`-b` は `--check` と併用しても無視される。

### 環境変数

**利用側プロジェクト**のルートに `.claude-container.d/env` を置くと起動前に自動で読み込まれる。読み込まれるのは `KEY=VALUE` 形式の行のみ（クォートやシェル展開は解釈されない。ホスト上でのシェル構文の即時解釈を避けるため、意図的に `source` していない。`PATH` 等の値経由の間接的な経路は別問題として [`#44`](https://github.com/jj1xgo/claude-container/issues/44) で追跡）。これはビルド時に焼き込まれる設定ではなく起動のたび毎回読み込まれるランタイム設定なので、変更してもリビルド（`-b`）は不要。

| 変数 | デフォルト | 説明 |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | `~` | `.claude.json` と `.claude/` が置かれているディレクトリ。後述「ホストの Claude Code 設定の読み取り専用保護」の基点でもある。絶対パスか `~/` 始まりで指定する（相対パスは起動を中止する） |
| `EXTRA_MOUNT` | `/dev/null` | コンテナ内 `/data` に追加でマウントするホスト側パス |
| `SHARED_MOUNT` | `/dev/null` | コンテナ内 `/shared` に追加でマウントするホスト側パス。複数プロジェクトからの共有ディレクトリ参照向け（`EXTRA_MOUNT` と併用可）。設定済みでパスが無い場合は起動を中止 |
| `TZ` | ホストから自動検出 | コンテナ内のタイムゾーン |
| `CLAUDE_CONTAINER_NO_FIREWALL` | (unset) | `1` でエグレス制限（後述）を無効化 |
| `GITCONFIG_FILE` | (unset) | コンテナ内 `~/.gitconfig` として read-only マウントするホスト側 git 設定ファイルのパス（後述） |
| `SECRETS_DIR` | (unset) | GitHub トークン等のシークレットをコンテナへ持ち込む唯一の機構のホスト側パス（後述「GitHub トークンの配線」節） |
| `CODEX_DIR` | (unset) | Codex CLI の認証情報ディレクトリ（`auth.json` 等）をコンテナへ rw マウントするホスト側パス。専用ディレクトリを推奨（後述「MCP サーバーの追加」節の Codex レシピ）。絶対パスか `~/` 始まりで指定する（相対パスは起動を中止する）。実ホストの `~/.codex` と同じ実体を指す指定（表記ゆれ・シンボリックリンクを含む）は起動を中止する |

`TZ` は起動スクリプトがホストの `/etc/timezone`（なければ `/etc/localtime` シンボリックリンク）から自動検出する。`.claude-container.d/env` で明示した場合はそちらが優先される。

claude-container 自身を対象プロジェクトとして自己ホスト起動する場合（このリポジトリを直接 `./claude-container` の引数に渡す場合）は、`.claude-container.d/env.example` をコピーして `.claude-container.d/env` を作成する。`SECRETS_DIR` 等ホスト固有のパスを含みうるため `.claude-container.d/env` は gitignore 対象で、リポジトリには example のみをコミットする。同様に、GitHub 公式 MCP サーバー（後述「GitHub トークンの配線」節のレシピ参照）を自己ホスト環境でも使いたい場合は、`.mcp.json.example` をコピーして `.mcp.json` を作成する（`.mcp.json` はメンテナ自身のセッション用実設定のため gitignore 対象）。

### 利用側プロジェクトの設定

bash history はターゲットプロジェクトの `.claude/bash_history` に保存される。誤ってコミットしないよう、ターゲットプロジェクトの `.gitignore` に以下を追加することを推奨する。

```
.claude/bash_history
```

利用側プロジェクトの claude-container 向け設定は `.claude-container.d/` ディレクトリに一本化されている。中身は「起動のたび読み込まれるランタイム設定」と「ビルド時にイメージへ焼き込まれる設定」の2種類に分かれる。

```
.claude-container.d/env                  # ランタイム設定（KEY=VALUE、上記「環境変数」参照）。-b 不要、gitignore 対象
.claude-container.d/packages.txt         # apt パッケージ（1行1パッケージ、素のパッケージ名のみの allowlist 検証あり。行頭 # はコメント）。-b 必須、コミット対象
.claude-container.d/requirements.txt     # pip パッケージ（名前＋extras＋バージョン指定子のみの allowlist 検証あり。URL・パス・オプション行・環境マーカー・行内空白は拒否しビルド停止。行内 # 以降はコメントとして剥がされる）。-b 必須、コミット対象
.claude-container.d/allowed-domains.txt  # エグレス制限に追加する許可ドメイン（1行1ドメイン、# はコメント）。-b 必須、コミット対象
.claude-container.d/node-version.txt     # 導入する Node.js のバージョン（例: 22.14.0、1行のみ）。-b 必須、コミット対象
.claude-container.d/codex-version.txt    # 導入する Codex CLI のバージョン（例: 0.46.0 または latest、1行のみ）。-b 必須、コミット対象
.claude-container.d/allowed-ports.txt    # エグレス許可を限定するTCPポート（1行1ポートまたはport:port、# はコメント）。-b 必須、コミット対象
.claude-container.d/base-image.txt       # ベースイメージ（例: debian:testing、1行のみ）。-b 必須、コミット対象
```

`env` 以外は任意。`packages.txt`/`requirements.txt`/`allowed-domains.txt` を置かなければ claude-container 同梱のデフォルト（空のフォールバック）が使われる。`allowed-domains.txt` にはプロジェクトの作業に必要な追加ドメイン（例: pip なら `pypi.org` と、パッケージ本体の実ダウンロード先である `files.pythonhosted.org` の両方— index への到達だけでは `pip install` は完走しない）を書く。ビルド時にイメージへ焼き込まれるため、変更を反映するには `-b` での再ビルドが必要（`env` はこのビルド時焼き込みの対象外 — ホスト固有パスをイメージに含めないため）。

`allowed-ports.txt` は許可ドメイン（GitHub CIDR・`allowed-domains.txt` 指定分）への到達を許すTCPポートを既定の `443,22` から変更したい場合に使う（`jj1xgo/claude-container#31`）。置かなければ `443,22` が使われる（他の3ファイルと異なり WARNING は出ない — `node-version.txt`/`codex-version.txt` と同じ任意機能の流儀）。この制限は許可ドメイン宛のルールにのみ適用され、DNS（53番）とホストネットワーク宛のルールには適用されない（後述「アーキテクチャ」節参照）。ポート数は `iptables` の `multiport` マッチの上限により最大15個まで。`443` は必ず含めること（api.anthropic.com・api.github.com への到達と起動時の自己検証に必要）、`80` は許可できない（起動時の自己検証が「api.github.com:80 へ到達できない」ことを遮断のプローブに使う）。どちらも範囲指定（`79:81` 等）で含む場合も同様で、違反するとコンテナ起動時に理由付きの ERROR で停止する（`jj1xgo/claude-container#49`）。

`node-version.txt` は apt の debian:stable では入手できない Node.js バージョン（例: 22.x — trixie は 20.x、testing は 22 を飛ばして 24.x）が必要な場合に使う。nodejs.org 公式の Linux tarball を取得し、同梱の `SHASUMS256.txt` でチェックサム検証したうえで展開する。**ビルド時ネットワークは無制限のため、`allowed-domains.txt` に `nodejs.org` を追加する必要はない**（`init-firewall.sh` のエグレス制限はランタイムにのみ適用される）。置かなければ Node.js は導入されない（他の3ファイルと異なり、この場合は WARNING も出ない — 新設の任意機能であり、大多数のプロジェクトが使わないのが正常な状態のため）。

`codex-version.txt` は OpenAI の Codex CLI（`@openai/codex`）を諮問・レビュー用のセカンドオピニオンとして導入したい場合に使う。`node-version.txt` と同じ任意のオプトインファイルで、置かなければ導入されず WARNING も出ない。npm 経由でグローバルインストールするため **npm が必要** — `node-version.txt` を併せて設定するか、`packages.txt` に `nodejs`/`npm` を追加すること（npm が無いままバージョンを指定するとビルドがエラーで停止する）。固定バージョン（例: `0.46.0`）の代わりに `latest` と書くと、Claude Code 本体と同じく `-b` リビルドのたびに npm の `latest` dist-tag を再解決してインストールし直す（このケースだけ専用のキャッシュ破棄が働く）。`node-version.txt` は nodejs.org 公式 tarball の SHA256 照合が前提のため `latest` は使えない（バージョン固定のみ）— この非対称は両ファイルの導入方式の違いによるもの。MCP サーバーとしての使い方は後述「MCP サーバーの追加」節の Codex レシピを参照。

`base-image.txt` はベースイメージをホスト環境に合わせたい場合に使う（例: `debian:testing`。内部運用issue参照）。置かなければ既定の `debian:stable` が使われる（他の3ファイルと異なり WARNING は出ない）。許容範囲は **docker.io の debian 公式イメージのみ**（タグは自由、`debian:stable@sha256:<64桁hex>` のような digest pin も可）。範囲外の値は起動を拒否する（fail-closed）。この制限は「セキュリティ境界」ではなく「サポート範囲の宣言・互換性ガード」と位置づけている — `.claude-container.d/` を書き換えられる主体は `packages.txt` 経由で apt の maintainer script をビルド時 root で実行でき、`requirements.txt` 経由の任意 PyPI 名指定でも sdist の `setup.py` がビルド時 root で実行される経路が原理的に残る（PyPI は open publishing のため）。いずれもベースイメージ名だけを縛る防御効果は限定的（Codex 諮問による指摘、内部運用issue参照）。実際の互換性は `Dockerfile.claude` 側のビルド時アサーション（`setpriv`/`tini` の存在・`setpriv --ambient-caps`/`--inh-caps` の受理・apt sources の HTTPS 化）が担保する。ただしこのアサーションは「正直な壊れ方」しか検知できず、悪意を持って `setpriv` 等を偽装するベースイメージは検知できない。`debian:testing`/`debian:sid` のような rolling suite を指定すると、`-b` のたびに未知の apt パッケージ版へ追随するため再現性が下がる — 再現性が必要な場合は日付タグ（`debian:trixie-20260701`）か digest pin を使うこと。値の検証はホスト側の `claude-container` スクリプトが行うため、`podman build` を直接実行する経路では効かない。

### GitHub トークンの配線

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

### MCP サーバーの追加

`.mcp.json` は claude-container が用意する機構ではなく、Claude Code 本体が標準で持つ「プロジェクトルート（`/workspace` 直下）の `.mcp.json` を project-scoped server として自動読み込みする」機能である。そのためタイプ（http／stdio）に応じて、以下の範囲は**claude-container 側を一切変更せず利用側プロジェクトの設定だけで追加できる**。

**http／sse タイプ**（リモートエンドポイントに直接接続するサーバー。例: GitHub 公式 MCP サーバー、具体的な設定例は前述「GitHub トークンの配線」節の「GitHub 公式 MCP サーバーを使う場合のレシピ」を参照）:

1. ターゲットプロジェクト直下に `.mcp.json` を置く（Claude Code が自動で読み込む）
2. 認証が必要なら `SECRETS_DIR/export/` に任意の名前でトークンファイルを置き（前述「GitHub トークンの配線」節参照）、`.mcp.json` 側で `${変数名}` として参照する
3. 接続先ドメインを `.claude-container.d/allowed-domains.txt` に追加する（ビルド時焼き込みのため `-b` での再ビルドが必要）

**stdio タイプ**（コンテナ内でコマンドとして起動するサーバー）は、この一存では追加できない。`entrypoint.sh` が起動時に `/workspace/.mcp.json` を監査し、`command` フィールドを持つサーバーを検知するとサーバー名・実行コマンドを表示した上で対話確認（TTY 入力）を求める。確認できない場合（非対話起動、または拒否）は起動を中止する（fail-closed）。

この確認を挟む理由: stdio タイプのサーバーは、`npx` 等によるネットワーク越しの取得を経ずリポジトリに同梱されたコードとして実行できるため、http タイプと違ってファイアウォール・再ビルドという既存の壁を通らない。`--dangerously-skip-permissions` 下では Claude Code 本来の MCP 承認プロンプトも機能しないため（後述「セキュリティモデル」節）、この対話確認が唯一の壁になる。**環境変数による opt-out は用意していない**: `.claude-container.d/env` は保護変数（`readonly`）を除く全キーが export される設計のため、opt-out 変数もリポジトリ自身が書けてしまい、悪意あるリポジトリに対するゲートとして意味を成さない。

stdio タイプのサーバーをどうしても使いたい場合は、`npx` 等の実行時取得（＝セッション開始のたびネットワーク越しに未検証のコードを取得する経路）でなく、`.claude-container.d/packages.txt` 等によるビルド時焼き込み、またはホスト側インストール＋bind mount（`EXTRA_MOUNT` 等）で導入することを推奨する。**`packages.txt` 経路ではバージョン固定ができない**（`pkg=version` 形式のバージョンピンは allowlist 検証で拒否される）ため、バージョン固定が必要な場合は bind mount 経路を採ること。あわせて、npm レジストリ（`registry.npmjs.org` 等）を `allowed-domains.txt` へ追加しないこと — 追加すると `npx` 経由の実行時取得が成立し、上記の対話確認を毎回強制されるだけでなく、取得するコード自体の検証が効かなくなる。

**TOFU（Trust On First Use）による確認の省略**（claude-container#28）: 対話確認で `y` と回答すると、`claude-container` スクリプトが承認時点の stdio サーバー定義のハッシュを、ホスト側 `~/.local/state/claude-container/mcp-approvals/<project>` に記録する（`.mcp.json` 自体やコンテナ内には保存しない — コンテナ側から改変できない場所に置くのが目的）。次回以降の起動では、`.mcp.json` の stdio サーバー定義がこの記録と一致する限り対話確認を自動的にスキップし、定義が変化した場合のみ再度確認を求める。記録はプロジェクトごとに独立しており、`--clean <directory>` で当該プロジェクト分のみ、引数なしの `--clean` で全プロジェクト分をまとめて削除できる。

なお `claude mcp add` によるローカル／ユーザースコープの登録（`~/.claude.json` 側）はこのゲートの対象外である。これはリポジトリ側が制御できないファイルへの登録のため「悪意あるリポジトリの初回起動」という脅威モデルには当てはまらず、各プロジェクトの利用者が自己管理する範囲になる。

**Codex CLI をセカンドオピニオン用 MCP サーバーとして使う場合のレシピ**（`stdio` タイプの具体例。内部運用issue参照）:

1. ターゲットプロジェクトの `.claude-container.d/codex-version.txt` に導入したい Codex のバージョン（例: `0.46.0`）または `latest` を書く（前述「利用側プロジェクトの設定」節）。npm が必要なため `node-version.txt` も併せて設定する
2. ターゲットプロジェクトの `.claude-container.d/allowed-domains.txt` に `chatgpt.com` を追加する。ChatGPT アカウント認証（`auth.json`）を使う Codex は API 呼び出し先を `https://chatgpt.com/backend-api/` にハードコードしており（[openai/codex](https://github.com/openai/codex) `codex-rs/model-provider-info/src/lib.rs` の `CHATGPT_CODEX_BASE_URL` 等）、許可しないとエグレスファイアウォールに阻まれて呼び出しが失敗する
3. ホストに Codex 専用の認証情報ディレクトリを用意し、`~/.codex/auth.json`（ホストで `codex login` 済みのもの）を1回だけシードコピーする。**ホストの実 `~/.codex` を `CODEX_DIR` にそのまま指定しないこと** — auth.json の自動リフレッシュ書き戻しのため rw マウントが必須であり、実ディレクトリを共有するとコンテナ側のコードが `config.toml`（`notify` フック等）を書き換えられ、ホストで Codex を起動した際に任意コマンドが実行される経路になる（詳細は `.claude-container.d/env.example` の該当コメント参照）:
   ```
   mkdir -p -m 700 ~/.codex-container
   cp ~/.codex/auth.json ~/.codex-container/auth.json
   chmod 600 ~/.codex-container/auth.json
   ```
4. ターゲットプロジェクトの `.claude-container.d/env` に `CODEX_DIR=~/.codex-container` を設定する（`-b` 不要、ランタイムマウント）
5. ターゲットプロジェクトの `.mcp.json` に以下のように書く（`codex mcp-server` は stdio 型のため、初回起動時に前述の対話確認〈TOFU〉が発火する）:
   ```json
   {
     "mcpServers": {
       "codex": {
         "command": "codex",
         "args": ["mcp-server"]
       }
     }
   }
   ```
6. `-b` での再ビルドが必要（`codex-version.txt`/`allowed-domains.txt` はいずれもビルド時焼き込み設定のため）

**運用上の注意**: MCP サーバー経由の呼び出しは Claude Code 側が `cwd` を明示的に渡す必要があり、渡し忘れると意図しない `AGENTS.md` が拾われるリスクがある（[openai/codex#12128](https://github.com/openai/codex/issues/12128)）。諮問時は `/workspace` を起点にする運用を徹底すること。また auth.json のリフレッシュフローには既知の不具合報告（[openai/codex#15502](https://github.com/openai/codex/issues/15502)）があり、この領域は枯れていない可能性がある点に留意する。

### アーキテクチャ

主要ファイルが連携して動作する。

- **`claude-container`**（bash）— エントリーポイント。絶対パスを解決し、ターゲットプロジェクトのディレクトリ名（basename）をサニタイズした文字列に絶対パスの sha256 先頭8文字を付与した `PROJECT_NAME` を算出する（例: `myproject-3f2a9c1b`）。これによりイメージ名（`localhost/<PROJECT_NAME>_claude-auth-workspace`）とビルドコンテキストのステージング先（`.build-context/<PROJECT_NAME>/`）をプロジェクトごとに分離し、`podman compose -p "$PROJECT_NAME"` でプロジェクト名を明示する。以前は全プロジェクト共通の固定イメージ名・固定ステージング先だったため、異なるプロジェクトを交互にビルドすると後勝ちで上書きされる問題があった。`.claude-container.d/env` の `KEY=VALUE` 行を読み込み、`TZ` を自動検出した上で `CONTEXT` / `CLAUDE_CONTAINER_DIR` を設定して `podman compose run` に委譲する。`-b` 指定時は `podman compose build` を `run` とは別ステップで実行する — `run --build` はビルド失敗時に既存の古いイメージへフォールバックしてしまう（fail-open）ため、分離して失敗時は起動へ進ませない（fail-closed）。ビルド前に、プロジェクト側の `.claude-container.d/packages.txt`・`requirements.txt`・`allowed-domains.txt`（無ければ claude-container 同梱のデフォルト）・`node-version.txt`・`codex-version.txt`・`allowed-ports.txt`（無ければ空ファイルを都度生成。他の3ファイルと異なり同梱のデフォルトファイルは持たず、WARNING も出さない）と `entrypoint.sh`・`init-firewall.sh`・`git-askpass.sh`・`validate-build-input.sh`・GitHub meta スナップショット（後述）をこのプロジェクト専用の `BUILD_CONTEXT_DIR` に集約する（`-b` 指定時、またはイメージ未ビルド時のみ実行）。`--clean <directory>` はそのプロジェクト分のイメージ・ネットワーク・ビルドコンテキストのみを、`--clean`（引数なし）は実在する claude-container イメージ全てを走査して全プロジェクト分を削除する（レガシーの単一共有イメージ `localhost/claude-container_claude-auth-workspace` も同じ命名パターンで検出されるため、旧バージョンからの移行時は `--clean` の実行だけで回収できる）。
- **`compose.yml`** — サービス `claude-auth-workspace` を定義。ビルドコンテキストは `${BUILD_CONTEXT_DIR}`（上記でステージングされたディレクトリ）、Dockerfile は `${CLAUDE_CONTAINER_DIR}/Dockerfile.claude` を参照する。ホストの `~/.claude.json` と `~/.claude/`（認証・設定）、対象ワークスペース（`/workspace`）、`/etc/localtime`（タイムゾーン）をマウントする。`userns_mode: keep-id` でコンテナ内ファイルのオーナーをホストユーザーに合わせる。`cap_add` で `NET_ADMIN`/`NET_RAW` を付与し、`init-firewall.sh` がコンテナのネットワーク名前空間に iptables ルールを設定できるようにする（rootless podman + `userns_mode: keep-id` ではこれらが非root ユーザー `node` の ambient set にも入り全子プロセスへ継承されるため、`Dockerfile.claude` の `ENTRYPOINT`（次項）で剥奪する。後述「セキュリティモデル」節参照）。`sysctls` で `net.ipv6.conf.{all,default}.disable_ipv6=1` を設定し、IPv6 をカーネルレベルで無効化する（後述）。`CODEX_DIR` を設定した場合は Codex CLI の認証情報ディレクトリを rw でマウントする（他のオプトインマウントと異なり `:ro` を付けない — auth.json のトークンリフレッシュ書き戻しのため。前述「MCP サーバーの追加」節の Codex レシピ参照）。
- **`Dockerfile.claude`** — 既定 `debian:stable`（`.claude-container.d/base-image.txt` で上書き可、前述「利用側プロジェクトの設定」参照。`FROM` は `COPY` より先に評価されるためファイルを直接読めず、`ARG BASE_IMAGE` 経由で受け取る）をベースにビルド。`ca-certificates` を HTTP でインストール後、apt ソースの全 URI を HTTPS に書き換えてから残りのパッケージを取得する（ホスト名リテラルではなく結果ベースで書き換えるため、ミラーが異なっても無言で no-op にならない）。固定 apt レイヤーの直後に、ベースイメージ可変化に伴うビルド時アサーション（`setpriv`/`tini` の存在・`setpriv --ambient-caps`/`--inh-caps` の受理・apt sources に `http://` が残っていないこと）を fail-closed で実行し、境界機構の土台が壊れたまま静かにビルドが成功する事態を防ぐ。Claude Code は公式 native installer（`curl -fsSL https://claude.ai/install.sh | bash`）でインストール。非 root ユーザー `node`（UID 1000、明示的に作成）で動作し、`CMD ["/usr/local/bin/entrypoint.sh"]`（次項参照。root 所有の `/usr/local/bin` に境界アセットとして配置され、node からは書き換えられない）を実行する。`node:24`（約 1.1 GB）から切り替えた理由: native installer は glibc のみ依存で実行時に Node.js を必要としないため、軽量な Debian ベースで十分。slim ではなく full 版を使う理由: full 版には `ca-certificates` 等の基本パッケージが含まれており apt 周りの初期設定が最小限で済む。`ENTRYPOINT` は `setpriv --ambient-caps=-all --inh-caps=-all /usr/bin/tini --` で、`tini` の起動前に ambient/inheritable capability を全プロセスツリーから剥奪する（`setpriv` は exec するため居残らず、tini は PID1 のまま）。これにより `compose.yml` の `cap_add` が非root ユーザーの ambient set にも入る問題（前項参照）を打ち消し、`NET_ADMIN`/`NET_RAW` の実消費者を `sudo` 経由の `init-firewall.sh`（root、bounding set 由来）のみに限定する。tini を PID1 に据えるのは、claude 自身が PID1 だと、PID1 に再親付けされた子プロセス（ファイアウォール更新ループの sudo 補助プロセス等）が reap されずゾンビとして蓄積し、さらに claude が終了時にハングした場合（2026-07-02 に実障害: ホストカーネルの workqueue Oops により kill 不能な D 状態スレッドが残存）は PID1 自体が reap 不能なゾンビとなり、crun がシグナルを配送できず（`crun kill ... failed` / "No such process"）`podman stop` でもコンテナを回収できなくなる。tini を PID1 に置くことで reap と `podman stop` が機能し続ける（カーネル側のハング自体は tini でも防げない）。`tini` は `packages.txt` に入れず Dockerfile 固定のパッケージ行に含める — プロジェクト側 `.claude-container.d/packages.txt` で上書きされて消えるのを防ぐため。`node-version.txt` ブロックの直後には、同じ任意オプトインの流儀で Codex CLI（`@openai/codex`）を npm 経由で導入するレイヤーがある（`codex-version.txt` で指定、npm 不在時はビルドをエラーで止める。詳細は内部運用issue参照）。`packages.txt`/`requirements.txt` の取り込みも `validate-build-input.sh` による allowlist 検証を `apt-get`/`pip3` の実行より前に置く同格の fail-closed 検証で、setpriv/tini アサーションと同じく境界機構の土台が壊れたまま静かにビルドが成功する事態を防ぐ（前述「利用側プロジェクトの設定」参照）。
- **`entrypoint.sh`** — コンテナの `CMD`（PID1 は上記 tini、このスクリプトと `exec` 先の claude はその子として動く）。起動時に `init-firewall.sh` でエグレス制限を適用し（失敗時は起動を中断）、バックグラウンドでドメイン再解決ループ（約15秒間隔、次項参照）を開始したうえで `claude --dangerously-skip-permissions` を起動する。あわせて `~/.claude/plugins/` 内に残るホスト側のパスをコンテナ内パスへ自動修正し、`/workspace/.mcp.json` を監査して stdio タイプの MCP サーバーを検知した場合は対話確認を要求する（fail-closed。詳細は「MCP サーバーの追加」節参照）。
- **`init-firewall.sh`** — コンテナ起動時に root（sudo）で実行されるエグレス制限スクリプト。Anthropic 公式 devcontainer の同名スクリプトの移植で、iptables により「許可したドメイン以外への外向き通信を遮断」する（deny-by-default）。Claude Code に必要なエンドポイント（api.anthropic.com・GitHub 等）とプロジェクト指定の `allowed-domains.txt` のみ許可する。許可ドメイン宛のルール（GitHub CIDR・タグ付きドメインルール）はさらに TCP ポートを `allowed-ports.txt` で指定した範囲（既定 `443,22`）へ限定する（`jj1xgo/claude-container#31`）。この制限は許可ドメイン宛のルールにのみ適用され、DNS（53番、指定リゾルバ限定）とホストネットワーク宛のルール（ゲートウェイ単一IPのみ許可、`/24` 全体ではない）は対象外（それぞれ別の理由でスコープが絞られているため）。GitHub IP レンジは起動時にライブ取得せず、ビルド時に焼き込まれたスナップショットを読み込むだけ（詳細は下記「GitHub meta スナップショット」参照）。設定後に example.com へ到達**できない**こと・api.github.com / api.anthropic.com へ到達**できる**こと・許可ドメイン上の非許可ポート（api.github.com:80）へ到達**できない**ことを自己検証する（GitHub 側は API クォータを消費しない TCP 接続確認）。失敗時はコンテナを起動しない（fail-closed）。ただし、許可ドメイン（`allowed-domains.txt` 指定分を含む）が恒久的に存在しない場合（NXDOMAIN）は警告に留め起動を継続する（一時的な解決失敗は従来どおり fail-closed）。IPv6 は `compose.yml` の `sysctls` で無効化するのが主対策だが、それが効かない環境向けに本スクリプト自身も `/proc/sys/net/ipv6/conf/*/disable_ipv6` への書き込みをフォールバックとして試みる（失敗しても警告のみで起動は継続する）。いずれの結果にかかわらず、既存の `ip6tables` による IPv6 全遮断（許可リストが A レコードのみのため）は最終防衛線として維持する。許可ドメインの IP は `entrypoint.sh` が起動するバックグラウンドループにより約15秒間隔で再解決され（`init-firewall.sh --refresh-domains`）、新しい IP を差分追加・約3分間見つからない IP を個別削除することで、CDN の短い TTL による IP ローテーションに追従する（チェーン全体のフラッシュは行わないため、更新中に新規接続が失敗する窓は作らない）。
- **`validate-build-input.sh`** — `packages.txt`/`requirements.txt` の正規化・照合を担う POSIX sh スクリプト。ビルド時（`Dockerfile.claude` の `RUN`）・起動前診断（`--check`）・テスト（`test-build.sh`）の3者が同じスクリプトを呼ぶことで、検証ロジックが複数箇所へ複製されドリフトする事態を防ぐ（`claude-container#34`）。責務は正規化と照合のみで、インストール・ネットワークアクセスは行わない。
- **`packages.txt`** / **`requirements.txt`** / **`allowed-domains.txt`** — claude-container 同梱のデフォルト apt/pip パッケージ・許可ドメイン一覧（フォールバック既定値）。プロジェクト側で上書きする場合は `.claude-container.d/` を使う（「利用側プロジェクトの設定」参照）。`node-version.txt`・`allowed-ports.txt` にはこの種の同梱デフォルトは無く、プロジェクト側に無ければ `claude-container` がビルドコンテキスト内に空ファイルをその場で生成する（前者は Node.js 未導入、後者は `init-firewall.sh` 自身が既定値 `443,22` を適用する、という意味。いずれも警告は出さない）。`codex-version.txt` も同じ扱い（Codex CLI 未導入、警告なし）。

#### GitHub meta スナップショット

`init-firewall.sh` の許可リストが使う GitHub IP レンジは `https://api.github.com/meta` から取得する。未認証 GitHub API のレート制限（60 req/h/IP）を避けるため、取得は `claude-container` のビルドコンテキスト準備時（`-b` のたび最大1リクエスト）に1箇所だけで行い、`Dockerfile.claude` がその結果をイメージへ焼き込む。コンテナ起動のたびのライブ取得は行わないため、何度再起動してもレート制限は消費しない。取得に失敗した場合は (1) このプロジェクトの前回ステージング分（`.build-context/<PROJECT_NAME>/` に残っている）、(2) それも無ければ他プロジェクトの最新スナップショット（GitHub の IP レンジは変更頻度が低いため実用上問題ない）を警告付きで再利用し、いずれも無い場合のみビルドを中断する。

### イメージの変更

`Dockerfile.claude` を編集して `./claude-container -b /path/to/project` でリビルドする。`-b` を付けると GitHub meta スナップショットの再取得（上記）が試みられ、あわせて `CACHEBUST` にその時点のエポック秒が渡されて install レイヤーのキャッシュが必ず破棄される。これにより、`-b` のたびに `install.sh` が再実行されて最新版の Claude Code が取得される（apt パッケージ等の上位レイヤーはキャッシュを流用するため高速）。再現性が必要な場合は `compose.yml` で `CLAUDE_CODE_VERSION` を固定する。

`.claude-container.d/` のパッケージ一覧・許可ドメイン（`allowed-domains.txt`）・許可ポート（`allowed-ports.txt`）・Node バージョン指定（`node-version.txt`）・ベースイメージ指定（`base-image.txt`）を変更した場合も、イメージへ反映するには `-b` での再ビルドが必要。`entrypoint.sh`・`init-firewall.sh`・`git-askpass.sh`・`validate-build-input.sh`・`Dockerfile.claude` 自体などビルドコンテキストへステージされるスクリプトの変更も同様（前述「アーキテクチャ」節参照）。

`.build-context/` は claude-container リポジトリ直下に生成されるビルドコンテキストの生成物（`.gitignore` 対象）で、プロジェクトごとに `.build-context/<PROJECT_NAME>/` のサブディレクトリへ分離される。`./claude-container --clean /path/to/project` でそのプロジェクト分のみ、`./claude-container --clean`（引数なし）で全プロジェクト分をまとめて削除できる。

Claude Code の自動アップデートは `compose.yml` の `DISABLE_AUTOUPDATER: "1"` で無効化している。コンテナは `--rm` で起動するためアップデートを取得しても終了時に消えるためで、バージョン更新は `-b` でのリビルドで行う。

### コンテナ間の永続化

コンテナは `--rm` で起動するため終了時に内部の状態は消えるが、以下の常時マウントはホストに bind mount されているため**コンテナを再起動しても保持される**（`EXTRA_MOUNT`/`SHARED_MOUNT`/`SECRETS_DIR` 等の opt-in マウントは、設定した本人がホスト側に同じパスを維持する限り同様に保持されるが、任意設定のためここには含めない — 一覧は「環境変数」節参照）。

| コンテナ内パス | ホスト側 | 内容 |
|---|---|---|
| `/home/node/.claude/` | `~/.claude/` | Claude のメモリ・設定・セッション履歴 |
| `/home/node/.claude.json` | `~/.claude.json` | Claude の認証情報 |
| `/workspace/` | 起動時に指定したディレクトリ | 作業対象プロジェクト |

### 何ができて何ができないか（git / gh / PAT / hook 早見表）

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
| user scope の設定 11 項目: `hooks/` `skills/` `plugins/` `commands/` `agents/` `workflows/` `rules/` `output-styles/` `settings.json` `CLAUDE.md` `statusline.sh` | 読める・**書けない**（`:ro` 重ねマウント。作成・更新・削除・`/plugin` の install/update・これらへ保存される設定変更はホスト側で行う。ホスト側で更新した内容はコンテナ再起動で反映される） |
| 認証（`.credentials.json`）・transcript（`projects/`）・auto memory（`projects/<p>/memory/`）・`history.jsonl` 等の状態 | 読み書き可（従来どおり） |
| project scope の設定（`/workspace/.claude/` 配下の settings・skills・agents・commands・rules・CLAUDE.md、`.mcp.json`） | 読み書き可（従来どおり。ホスト側での扱いは「セキュリティモデル」節参照） |

**hook による追加制限**

この保護は `examples/hooks/block-pr-approve.sh` として本リポジトリに同梱されているが、プロダクト本体には配線されていない。適用するには、対象プロジェクトの `.claude/settings.json` に自分で配線する（設定例・回帰テストは `examples/hooks/README.md` を参照）。フォークにもファイル自体はそのまま同梱されるが、配線しない限り動作しない。

| 機構 | ブロックするもの | 通すもの |
|---|---|---|
| PreToolUse hook `examples/hooks/block-pr-approve.sh` | `gh pr review --approve`（短縮形 `-a`、短オプションクラスタ内の `a` を含む）／ `gh api …/pulls/<N>/reviews` への `event=APPROVE`（引用符・ヒアドキュメント本文経由を含む） | `--comment`・`--request-changes` 等その他の PR 操作、および gh コマンド全般 |
| `permissions.deny` | （現状未使用 — この保護の機構は上記 hook のみ） | — |

- **役割分担の基準**: `permissions.deny` はコマンドプレフィックス/glob の静的パターンで丸ごと禁止できる場合に向く。本件は「`gh pr review` のうち `--approve` だけ拒否し `--comment` は通す」「生 API の `event=APPROVE` を JSON 本文・ヒアドキュメント内でも検出する」という文脈依存判定が必要で、deny の glob では過剰ブロックか検出漏れのどちらかになるため hook を採用している
- **既知の誤検知**: 残存 false positive（安全方向・許容）＝ 実行コマンドが `gh api` で、ヒアドキュメント本文に `pulls/N/reviews` と `event=APPROVE` の両方を引用したケース、複数行ダブルクォート文字列内の承認文字列。残存 false negative（脅威モデル外）＝ 引用文字列内の `<<X` でヒアドキュメント除去を誤爆させる意図的難読化。脅威モデルは「Claude 自身のうっかり自律承認の抑止」であり意図的な難読化は対象外
- **参照**: リスクの詳細は「セキュリティモデル」節、hook の実装詳細・配線例・回帰テストは `examples/hooks/README.md`

### セキュリティモデル

Claude は `--dangerously-skip-permissions` で起動するため、ツール使用の確認プロンプトなしに動作する。ガードレールはコンテナ境界 — マウントされたワークスペースと `/data`・`/shared` への読み書きアクセスを持つ。意図したプロジェクトスコープ外の機密データを含むディレクトリはマウントしないこと。`SHARED_MOUNT`（`/shared`）は同じホストパスを設定した全プロジェクトのコンテナが完全な rw アクセスを持つ共有領域のため、相互に信頼できるプロジェクト間でのみ設定すること。

ネットワークは既定で `init-firewall.sh` によるエグレス許可リストで制限される。Claude Code に必要なエンドポイント（Anthropic API・GitHub 等）と `.claude-container.d/allowed-domains.txt` で指定したドメイン以外への外向き通信は遮断されるため、悪意ある pip パッケージやプロンプトインジェクションが認証情報（`~/.claude.json`）やソースコードを任意の外部ホストへ送信することを防ぐ。開放が必要な場合は `.claude-container.d/env` に `CLAUDE_CONTAINER_NO_FIREWALL=1` を書いて無効化できる（自己責任）。

このガードレールが機能するのは、Claude（およびその子プロセス）がこの許可リスト自体を書き換えられないことが前提になる。`Dockerfile.claude` の `ENTRYPOINT`（前述「アーキテクチャ」節参照）でコンテナ起動時に関連 capability（`NET_ADMIN`/`NET_RAW`）を剥奪しており、iptables の実消費者は `sudo` 経由で root になった `init-firewall.sh` のみに限定される。file capabilities 付きバイナリの追加導入や `podman exec` 経由には限界が残る（[詳細](SECURITY-CLAIMS.md#c-1)）。

**制限しても残るリスク**: DNS クエリを使ったトンネリング、許可済みサービス（GitHub 等）自体への送信、CDN の共有 IP 経由の到達は原理上防げない。`/etc/resolv.conf` から IPv4 リゾルバを検出できない場合（通常の Podman 環境では稀）、DNS（53番ポート）は宛先無制限で許可される縮退動作になる（起動時に `WARNING: no IPv4 resolver in /etc/resolv.conf, allowing DNS to any host` が出力される）。許可ドメインの IP は約15秒間隔のバックグラウンド再解決で追従するが（上記アーキテクチャ節参照）、ローテーション直後からリフレッシュが反映されるまでの数十秒間は新規接続が失敗しうる（コンテナ再起動が必要だった以前と比べれば大幅に縮小されるが、ゼロにはできない）。GitHub IP レンジはビルド時スナップショット固定のため、コンテナ再起動では更新されず `-b` でのリビルドが必要。ビルド時（`pip3 install` 等）のネットワークは制限されない。

**`packages.txt`/`requirements.txt` のビルド時インジェクション対策にも残余がある**: 両ファイルは `validate-build-input.sh` による allowlist 検証を経る（前述「利用側プロジェクトの設定」「アーキテクチャ」節）が、PyPI は open publishing のため、`requirements.txt` の名前指定だけで任意パッケージの sdist に含まれる `setup.py` がビルド時 root で実行される経路が原理的に残る（`claude-container#34`）。apt 側は設定済みリポジトリ内のパッケージに限られるため同じ経路は無い。

**claude-in-chrome 連携はファイアウォールでは原理的に遮断できない**（`jj1xgo/claude-container#32`）: `.mcp.json` を介さないネイティブ機能のため MCP 監査ゲートの対象外で、コンテナ内から到達・実行可能である。ホスト側の通知は事前承認ではなく事後通知＋任意キャンセル（fail-open）で、コンテナ内のコードが人間の事前承認なしにホストの実ブラウザを操作しうる——「ガードレールはコンテナ境界」という前提の外側にある残存リスク（[詳細](SECURITY-CLAIMS.md#c-2)）。

**MCP サーバーの承認プロンプトは機能しない**: Claude Code 本来の仕様では project-scoped の `.mcp.json` サーバー利用前に承認プロンプトが表示されるが、`--dangerously-skip-permissions` 下ではこの確認が実行されないことを実機で確認済み（承認記録 `enabledMcpjsonServers` が空のままサーバーが稼働する）。stdio タイプ（コンテナ内でコマンドを実行するサーバー）は、この確認が無いままセッション開始と同時に人間・モデルどちらの判断も挟まず実行され、コンテナ内のトークン類を読めてしまうため、claude-container 側で `entrypoint.sh` による対話確認ゲートを設けている（前述「MCP サーバーの追加」節）。http／sse タイプはこのゲートの対象外だが、接続先はファイアウォールの許可リストが審査する。**残存する経路**: `claude mcp add` によるローカル／ユーザースコープの登録（`~/.claude.json` 側）はこのゲートの対象外で、既に侵害されたセッションによる永続化の手段になりうる。

**`.claude-container.d/env` は信頼できないリポジトリでは攻撃面になる**: `env` は保護変数（`readonly`）を除きキーを選ばず export される設計のため（前述「環境変数」節）、`CLAUDE_CONTAINER_NO_FIREWALL=1` のようなセキュリティ機構の opt-out 変数も、そのプロジェクト自身の `.claude-container.d/env` に書かれていれば有効になってしまう。信頼できないリポジトリを起動する前に `.claude-container.d/env` の中身を確認すること。

**`.mcp.json` にだけ追加ゲートがあるのは、入力の信頼度でなく帰結の重大性で線を引いているため**（`claude-container#29`）: リポジトリ同梱の設定（`.claude-container.d/env` と `.mcp.json` の両方）は、いずれも起動前に運用者がレビューする責任範囲にある——同じリポジトリに同梱される以上、どちらか一方だけを「信頼できる」「信頼できない」と区別する根拠は無い。claude-container が追加の対話ゲートを設けるのは、レビューを怠った場合の帰結が「セッション開始と同時の任意コード実行」になる場合に限る（＝ `.mcp.json` の stdio 型）。`env` のキーは `.mcp.json` の stdio 型サーバーのように「セッション開始と同時に」コードを実行するわけではないが、`PATH` 等の実行時名前解決に関わるキーを通じてホスト側でのコード実行に至りうる（[`#44`](https://github.com/jj1xgo/claude-container/issues/44)）。この経路は本ゲートの対象外である。別軸として、境界へ影響するキー（`EXTRA_MOUNT`・`SHARED_MOUNT`・`SECRETS_DIR`・`GITCONFIG_FILE`・`CODEX_DIR` 等。`PATH` のような実行時名前解決キーはこの一覧の対象外）の使用は起動時に一覧して気づけるようにしている（`guard_env_boundary_keys()`）。この可視化は fail-closed ではない——`env` は運用者自身が書く設定という前提は変えていないため。

起動時の可視化を実際に確認したい場合は `.claude-container.d/env` に `CLAUDE_CONTAINER_NO_FIREWALL=1`（または `EXTRA_MOUNT`/`SHARED_MOUNT`/`SECRETS_DIR`/`GITCONFIG_FILE`/`CODEX_DIR`）を書いて起動する。値そのものはログに出さず、キー名のみを一覧する。

**ホストの Claude Code 設定の読み取り専用保護**: ホストの `~/.claude`（`CLAUDE_CONFIG_DIR` 基点）はコンテナへ rw で bind mount される（認証情報・transcript の共有に必要）が、そのうちホスト側で実行・読込される user scope の設定 11 項目（前述「何ができて何ができないか」節の表）は、`compose.yml` が rw マウントの内側に `:ro` の bind mount を重ねることで、**この mount 経由では**コンテナ内から書き換えられない。侵害されたセッションがここへ hook・skill・plugin 等を書くと、ホストの Claude Code がそれを読み込み・実行する（user settings の hooks は file watcher で稼働中セッションにも反映される）ため。マウント先がホストに無いと podman がサブ uid 所有の実体を作って残骸になるので、`claude-container` が起動直前（全ガードと MCP 承認の後）に欠けている項目をユーザー権限で空のまま作り、その旨を `INFO:` で表示する（`--check` は作らず `[WARN]` で報告する）。11 項目のいずれかが symlink または型の違う実体（ディレクトリ予定位置にファイル等）だと起動を中止する。symlink を拒否するのは、`:ro` の子マウントはリンク先に付く一方でリンク自体は rw の親マウント内に残り、コンテナ内で削除して作り直せば書き込み可能な実体に置き換えられる（保護の迂回）ため。**限界**: (1) 保護はこの mount 経由に限る。`/workspace`（作業ディレクトリ）・`EXTRA_MOUNT`・`SHARED_MOUNT` が `~/.claude` を含む、または保護対象そのものを指す場合は別経路から書けるため、起動時に `WARNING` を出す（検出はパスの包含関係のみで、別マウント内部のリンク等は検出しない）。(2) project scope の設定（`/workspace/.claude/` 配下と `.mcp.json`）は対象外で、ホストでそのフォルダを trust 済みならホストの Claude Code がそれらを読み込む。(3) `~/.claude.json`（trust フラグ・user scope の MCP 登録）、auto memory（`projects/<p>/memory/`）、`agent-memory/`、`shell-snapshots/`、`session-env/` は対象外（Claude Code が実行時に書くため）。前 3 者はホスト側セッションへの指示の再注入経路になりうる。(4) 保護された参照元（`settings.json`・`CLAUDE.md` の import・hook や plugin が読む依存ファイル）が `~/.claude` の外や対象外領域を指していれば、その先は保護されない。(5) `.claude-container.d/env` の `PATH` 等によるホスト側実行経路（`#44`）は本保護と独立で、引き続き未対応。(6) ホスト側で 11 項目のファイルを rename で置換した場合、稼働中のコンテナは旧実体を見続ける（再起動で反映）。

`SECRETS_DIR`（前述「GitHub トークンの配線」節）を設定した場合、上記「許可済みサービス自体への送信」というリスクが受動的なものから能動的なものに変わる: プロンプトインジェクションや悪意あるパッケージがコンテナ内からトークンを読み取り（メイン PAT はファイルとして、MCP／issues 用 PAT は export された環境変数として）、そのスコープ内で GitHub 等に書き込める。緩和策は各 fine-grained PAT のスコープ最小化（対象リポジトリ限定・短期限）で、被害を該当リポジトリでの操作に構造的に限定すること。設計上、export されるのは issues 限定等スコープを絞ったトークンのみに留め、広い権限は非 export（明示読みという一手間の壁の向こう）に置くことでこのリスクの既定値を下げている（「GitHub トークンの配線」節の設計原則参照）。`SECRETS_DIR` は汎用機構であるため、この能動的リスクは GitHub トークンに限らず持ち込んだ全シークレットに及ぶ（1コンテナに持ち込むのは実際に使う最小本数に留めること — 前述）。

`CODEX_DIR`（前述「MCP サーバーの追加」節の Codex レシピ）を設定した場合、コンテナ内のコードは Codex の認証情報（`auth.json`、ChatGPT アカウントのアクセストークン）を読める。`SECRETS_DIR` と異なり rw マウントのため、コンテナ側から書き込みも可能 — 専用ディレクトリ（実 `~/.codex` でない）を指定する設計により、汚染がホスト側の Codex 実行環境（`config.toml` の `notify` フック等）へ波及する経路を遮断している。Codex を stdio 型 MCP サーバーとして `.mcp.json` に登録する場合は前述の MCP 監査ゲート（TOFU）の対象になる。

`SECRETS_DIR/GITHUB_MAIN_PAT`（前述「git push を使う場合」）に `Contents: write` を付与した場合、能動的リスクは push・PRマージにも及ぶ: プロンプトインジェクションや悪意あるパッケージが、明示読み（`GH_TOKEN=$(cat "$GITHUB_MAIN_PAT_FILE") ...`）を介して対象リポジトリへの意図しないコミット・push・マージを引き起こしうる。非 export であることは「黙ってはできない」という一手間の壁ではあるが、コンテナ内の任意のプロセスがそのファイルパスを読める以上、確実な壁ではない。緩和策は他のトークン同様スコープ最小化（対象リポジトリ限定）に加え、GitHub 側の branch protection（force-push 禁止・レビュー必須化）を組み合わせること。

自リポジトリ向けのメイン PAT に `Pull requests: Read and write` を付与した場合の追加リスク:

- **攻撃対象面の拡大**: 他者PRのタイトル・本文改変、レビュー依頼スパム、妨害目的のクローズが可能になる。Issue操作と同種だが一段重い
- **`Contents: write` を付与しない限りpush・PRマージには至らない**: PRマージ（`PUT …/pulls/{n}/merge`）に必要な権限は `Contents: write` であり、`Pull requests` 権限だけでは実行できない。ただしメイン PAT に `Contents: write` も付与している場合は、この境界は無い（push 節参照）
- **auto-merge 経由の境界迂回に注意**: PRレビュー承認（`gh pr review --approve`）は `Contents: write` なしで実行できる。対象リポジトリで auto-merge が有効な状態だと、コンテナ内トークンによる承認だけで required review 条件が満たされ GitHub 側が自動マージしてしまう可能性がある。auto-merge を無効に保つこと（1枚目の壁）に加え、同梱の PreToolUse hook（`examples/hooks/block-pr-approve.sh`、配線すれば）が承認操作の自律実行を機構的にブロックできる（2枚目の壁 — 適用範囲と限界は「何ができて何ができないか」節参照）。MCP 経由の承認（`mcp__github__pull_request_review_write` 等）はこの hook の検査対象外のため、MCP へは「GitHub トークンの配線」節の `permissions.deny` を別途の壁として使うこと

### Podman 固有の注意

- `userns_mode: keep-id` はホストユーザーの UID/GID をコンテナ内にマップする Podman 固有の機能。Docker に移植する場合は削除する。
- `--in-pod false` は Podman Compose がデフォルトでサービスを Pod にラップする挙動を抑制する。Docker Compose はこのフラグを無視する。

### 変更後の確認

テストスイートはない。スクリプトや Compose / Dockerfile を編集した後は以下で確認する。

```bash
./lint.sh
```

`lint.sh` は、リポジトリ内の bash スクリプト（gitignore 対象を除く追跡済み・未追跡ファイルから shebang で自動判定するため、スクリプトを追加・削除しても対象リストの更新は不要）への `bash -n` と `shellcheck`、および `podman compose -f compose.yml config` をまとめて実行する。shellcheck 未インストール時はエラーで失敗する（`sudo apt-get install shellcheck` で導入）。podman が無い環境（コンテナ内での開発時）では Compose 検証のみ警告付きでスキップされる。

`compose.yml` の `:ro` 重ねマウント、または `claude-container` の `prepare_claude_config_ro()` を編集した場合は、ビルド済みのテストイメージ `localhost/claude-test`（`./test-build.sh` の全実行で作られる）がある状態で `./test-build.sh --config-ro-only` を実行する。実物の `compose.yml` とイメージで 11 項目への書き込みが拒否されること、実物のランチャーが placeholder 作成・型検査・`--check` の無書き込み・compose への `CLAUDE_CONFIG_DIR` 受け渡しを正しく行うことを、それぞれ別のテストで確認する（両者を通した対話起動は手動で行う）。

`claude-container` のガード関数（`guard_*`・`prepare_claude_config_ro()`）を編集した場合は `./test-build.sh --launcher-only` を実行する。podman をダミーに置き換えた隔離環境（一時 `HOME`・空の環境変数）で実物のランチャーを起動し、各ガードの通常起動と `--check` の挙動、compose へ渡る環境変数を検証する。実 podman が不要なので、コンテナ内の開発セッションや CI からも回せる。通常の `./test-build.sh` にも含まれる。

`Dockerfile.claude`（`ENTRYPOINT` の `setpriv` ラップ）を編集した場合は `-b` でのリビルドと実機起動が必須（前述「セキュリティモデル」節参照）。コンテナ内セッションから `sudo` 無しの `iptables` 操作ができないことが正しい状態であり、ファイアウォールルール自体の確認は `podman exec --user root <container> iptables -S`（ホスト側から）で行う——セッション内からの `iptables -S` 単体実行は権限剥奪後には失敗するようになる。

### バージョニング

[Semantic Versioning](https://semver.org/lang/ja/) に従い、リリースは annotated git タグ（`vX.Y.Z`）で管理し、タグごとに `gh release create <tag> --notes-from-tag` でタグメッセージをそのまま流用した GitHub Release を作成する（CHANGELOG ファイルは作らない）。番号は利用者から見えるインターフェース（CLI 引数・`.claude-container.d/` の設定形式・デフォルト挙動）を基準に判定する:

- **MAJOR** — 後方互換性が壊れる変更（デフォルト挙動の変更、設定形式の削除・非互換化など、利用者が対応しないと従来どおり動かないもの）
- **MINOR** — 後方互換な機能追加（既存の使い方はそのまま動く）
- **PATCH** — 後方互換なバグ修正のみ

バージョン履歴は GitHub の [Releases ページ](https://github.com/jj1xgo/claude-container/releases)で一覧・購読できる（`git tag -n1` でも確認可能）。

### 参考

- [Running Claude Code CLI in a Container (Endpoint Dev Blog)](https://www.endpointdev.com/blog/2026/03/claude-code-cli-in-container/) — フォーク元作者 Seth Jensen によるコンテナ化の解説記事

### ライセンス

GPL-3.0。フォーク元（sethjensen1/claude-container）は MIT ライセンス。詳細は [LICENSE](LICENSE) を参照。

---

<a id="english"></a>

## English

A Podman-based Claude Code container environment, forked from [sethjensen1/claude-container](https://github.com/sethjensen1/claude-container).

Launches Claude Code by mounting any directory as `/workspace`, sharing the host's Claude credentials via Podman + Compose.

apt/pip packages are specified per-project via `.claude-container.d/` (see below) — the claude-container repo itself carries no project-specific packages.

- [Requirements](#requirements)
- [Usage](#usage)
- [Pre-launch Check (--check)](#pre-launch-check---check)
- [Environment Variables](#environment-variables)
- [Target Project Configuration](#target-project-configuration)
- [Adding MCP Servers](#adding-mcp-servers)
- [Architecture](#architecture)
- [Modifying the Image](#modifying-the-image)
- [Persistence Across Container Runs](#persistence-across-container-runs)
- [What Works and What Doesn't (git / gh / PAT / hook quick reference)](#what-works-and-what-doesnt-git--gh--pat--hook-quick-reference)
- [Security Model](#security-model)
- [Podman-specific Notes](#podman-specific-notes)
- [Verifying Changes](#verifying-changes)
- [Versioning](#versioning)
- [References](#references)
- [License](#license)

### Requirements

- [Podman](https://podman.io/) and `podman-compose`
- `~/.claude.json` (Claude credentials) must exist on the host

### Usage

```bash
# Launch Claude Code in any directory
./claude-container /path/to/project

# Force rebuild the image and launch
./claude-container -b /path/to/project

# Remove that project's image, network, and build context, then exit
./claude-container --clean /path/to/project

# Remove all projects' images, networks, and build contexts, then exit
./claude-container --clean

# Diagnose without launching (no directory: check every project in the launch ledger)
./claude-container --check
./claude-container --check /path/to/project
```

The script works via symlink — it resolves its own path using `readlink`. Launching or rebuilding different target projects, even interleaved, no longer overwrites each other's image or build context (see "Architecture" below). Multiple projects can also be run concurrently.

### Pre-launch Check (`--check`)

In a setup where multiple family projects launch by directly invoking this local repo's `claude-container` (internal ops issue), a breaking change (e.g. v3.0.0 dropping the old config format, or v4.0.0's token-wiring change) can leave a project unable to start until its config is updated — the fail-closed guards only surface this at launch time. `--check` diagnoses this without launching, listing the migration steps needed before a rebuild/launch.

```bash
# Diagnose every project recorded in the launch ledger (see below)
./claude-container --check

# Diagnose specific directories (multiple allowed)
./claude-container --check /path/to/project-a /path/to/project-b
```

- **Launch ledger**: every normal launch (excluding `--clean`/`--check`) automatically records the target directory's host absolute path in `~/.local/state/claude-container/projects` (no manual maintenance needed). Running `--check` with no arguments diagnoses every project in this ledger. `--clean <directory>` also removes that project from the ledger; `--clean` (no directory) removes the ledger file itself. Launching via a symlink vs. the real path records separate entries (same identity rule as `compute_project_name()`).
- **What's checked**: legacy token variables (e.g. `GH_TOKEN_FILE`), `SHARED_MOUNT`/`GITCONFIG_FILE`/`SECRETS_DIR`/`CODEX_DIR` existence and layout (e.g. leftover `noexport/`), permissions, presence of `packages.txt`/`requirements.txt`/`allowed-domains.txt`, whether the image is already built (only when `podman` is available), MCP audit gate approval state, and content validation of `packages.txt`/`requirements.txt`. **Launch-time guards and content validation run in separate modes**: the presence checks etc. above share the exact same guard functions used at normal launch time, so the diagnosis can't drift from actual launch behavior. Content validation (allowlist validation of `packages.txt`/`requirements.txt`) is a `--check`-only advisory diagnosis, called separately from the normal-launch enforcement point (the `RUN` in `Dockerfile.claude`) — but both call the same `validate-build-input.sh`, so the validation logic itself can't drift.
- **Non-interactive, target repo unchanged**: `--check` never prompts over TTY (an unapproved stdio-type MCP server is reported as "a confirmation prompt will appear at first launch" only). A ledger entry whose directory no longer exists is reported as FAIL without silently rewriting the ledger. **The guarantee's scope is "does not modify the target repository or `.build-context/`"** (content validation always creates working files under `/tmp` via `mktemp`, so "no writes" isn't unqualified).
- **Exit code**: non-zero if any diagnosed project has a FAIL, zero otherwise. `-b` is ignored when combined with `--check`.

### Environment Variables

Place a `.claude-container.d/env` file at the root of the **target project** to have it read automatically before launch. Only `KEY=VALUE` lines are honored (no quoting or shell expansion — the file is deliberately NOT `source`d, to avoid immediate interpretation of shell syntax on the host; value-mediated paths such as `PATH` are a separate concern tracked in [`#44`](https://github.com/jj1xgo/claude-container/issues/44)). This is a runtime setting re-read on every launch, not something baked into the image, so changing it never requires a `-b` rebuild.

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | `~` | Directory containing `.claude.json` and `.claude/`. Also the base of the "read-only protection of host Claude Code settings" described below. Must be an absolute path or start with `~/` (a relative path aborts the launch) |
| `EXTRA_MOUNT` | `/dev/null` | Additional host path to mount at `/data` inside the container |
| `SHARED_MOUNT` | `/dev/null` | Additional host path to mount at `/shared` inside the container. For sharing a directory across multiple projects (can be used together with `EXTRA_MOUNT`). Launch is aborted if set but the path doesn't exist |
| `TZ` | Auto-detected from host | Timezone inside the container |
| `CLAUDE_CONTAINER_NO_FIREWALL` | (unset) | Set to `1` to disable the egress firewall (see below) |
| `GITCONFIG_FILE` | (unset) | Path on the host to a git config file to mount read-only as `~/.gitconfig` inside the container (see below) |
| `SECRETS_DIR` | (unset) | Host path to the sole mechanism for bringing GitHub tokens and other secrets into the container (see "GitHub Token Wiring" below) |
| `CODEX_DIR` | (unset) | Host path to the Codex CLI credentials directory (`auth.json` etc.), mounted rw into the container. Use a dedicated directory (see the Codex recipe under "Adding MCP Servers" below). Must be an absolute path or start with `~/` (a relative path aborts the launch). Any spelling that resolves to the real host `~/.codex` (including symlinks) aborts the launch |

`TZ` is auto-detected from the host's `/etc/timezone` (or `/etc/localtime` symlink). An explicit value in `.claude-container.d/env` takes precedence.

If you self-host claude-container against itself (passing this repo directly as the argument to `./claude-container`), copy `.claude-container.d/env.example` to `.claude-container.d/env`. It may contain host-specific paths (e.g. `SECRETS_DIR`), so `.claude-container.d/env` is gitignored and only the example is committed. Likewise, if you also want the GitHub official MCP server (see the recipe in "GitHub Token Wiring" below) in your self-hosted setup, copy `.mcp.json.example` to `.mcp.json` (`.mcp.json` holds the maintainer's own session config and is gitignored).

### Target Project Configuration

Bash history is saved to `.claude/bash_history` in the target project. To avoid accidentally committing it, add the following to the target project's `.gitignore`:

```
.claude/bash_history
```

Target-project-specific claude-container configuration lives entirely under `.claude-container.d/`. Files there fall into two categories: runtime settings (re-read on every launch) and build-time settings (baked into the image).

```
.claude-container.d/env                  # runtime settings (KEY=VALUE, see "Environment Variables" above); no -b needed, gitignored
.claude-container.d/packages.txt         # apt packages, one per line; allowlist-validated (bare package names only); leading # is a comment; requires -b, committed
.claude-container.d/requirements.txt     # pip packages; allowlist-validated (name + extras + version specifier only — URLs, paths, option lines, environment markers, and inline whitespace are rejected and fail the build); inline # onward is stripped as a comment; requires -b, committed
.claude-container.d/allowed-domains.txt  # extra domains for the egress firewall, one per line; # for comments; requires -b, committed
.claude-container.d/node-version.txt     # Node.js version to install (e.g. 22.14.0, single line); requires -b, committed
.claude-container.d/codex-version.txt    # Codex CLI version to install (e.g. 0.46.0 or latest, single line); requires -b, committed
.claude-container.d/allowed-ports.txt    # TCP ports the egress firewall permits, one per line or port:port; # for comments; requires -b, committed
.claude-container.d/base-image.txt       # base image (e.g. debian:testing, single line); requires -b, committed
```

All except `env` are optional. If `packages.txt`/`requirements.txt`/`allowed-domains.txt` are absent, claude-container's bundled defaults (empty fallbacks) are used. `allowed-domains.txt` lists extra domains the project needs (e.g. for pip: both `pypi.org` and `files.pythonhosted.org` — the latter serves the actual package downloads, so reaching the index alone isn't enough for `pip install` to succeed). These three are baked into the image at build time, so changing them requires a `-b` rebuild (`env` is deliberately excluded from this baking — it may hold host-specific paths that must never end up in the image).

`allowed-ports.txt` changes which TCP ports are reachable on allowed domains (GitHub CIDRs and `allowed-domains.txt` entries) from the default `443,22` (`jj1xgo/claude-container#31`). If absent, `443,22` is used — unlike the other three files, no WARNING fires (same opt-in convention as `node-version.txt`/`codex-version.txt`). This restriction applies only to allowed-domain rules; it does not apply to DNS (port 53) or the host-network rule (see "Architecture" below). At most 15 ports/ranges, per `iptables`' `multiport` match limit. `443` must be included (api.anthropic.com, api.github.com and the startup self-check need it) and `80` cannot be allowed (the startup self-check uses "api.github.com:80 is unreachable" as its blocked-port probe); both also apply when a range (e.g. `79:81`) covers the port, and a violation stops the container at startup with an ERROR stating the reason (`jj1xgo/claude-container#49`).

`node-version.txt` is for Node.js versions apt can't provide on debian:stable (e.g. 22.x — trixie ships 20.x, testing skips straight to 24.x). It fetches the official Linux tarball from nodejs.org and verifies it against nodejs.org's own `SHASUMS256.txt` before extracting. **Build-time network is unrestricted, so no `allowed-domains.txt` entry for `nodejs.org` is needed** (the `init-firewall.sh` egress restriction only applies at runtime). If absent, no Node.js is installed — and unlike the other three files, no WARNING fires in this case (it's a new opt-in feature; not having it is the normal state for most projects).

`codex-version.txt` opts into installing OpenAI's Codex CLI (`@openai/codex`) as a second-opinion advisor for consultation and review. Same opt-in design as `node-version.txt`: absent means not installed, no WARNING either. Installed via npm, so **npm is required** — set `node-version.txt` too, or add `nodejs`/`npm` to `packages.txt` (the build fails with an error if a version is specified but npm is missing). Write `latest` instead of a pinned version (e.g. `0.46.0`) to re-resolve npm's `latest` dist-tag and reinstall on every `-b` rebuild, same as Claude Code itself (this case gets its own cache-bust). `node-version.txt` can't do this — it relies on SHA256-verifying a specific nodejs.org tarball, so it only accepts pinned versions; this asymmetry follows from how each is installed. See the Codex recipe under "Adding MCP Servers" below for how to wire it up as an MCP server.

`base-image.txt` lets you match the base image to your host environment (e.g. `debian:testing`; internal ops issue). If absent, the default `debian:stable` is used — unlike the other three files, no WARNING fires. The allowed range is **docker.io's official debian image only** (any tag; digest pins like `debian:stable@sha256:<64-hex>` are also accepted). Out-of-range values are rejected at launch (fail-closed). This restriction is positioned as a **supported-range declaration / compatibility guard, not a security boundary** — anything that can write to `.claude-container.d/` can already run arbitrary apt maintainer scripts as root at build time via `packages.txt`, and naming an arbitrary PyPI package via `requirements.txt` can still run its sdist's `setup.py` as root at build time (PyPI is open publishing, so this path is inherent). Either way, restricting the base image name alone has limited defensive value (per Codex consultation, internal ops issue). Actual compatibility is enforced by build-time assertions in `Dockerfile.claude` (presence of `setpriv`/`tini`, `setpriv --ambient-caps`/`--inh-caps` support, apt sources rewritten to HTTPS) — but these only catch honest breakage, not a base image that maliciously fakes those commands. Pointing this at a rolling suite (`debian:testing`, `debian:sid`) means every `-b` rebuild picks up whatever apt package versions are current, reducing reproducibility — use a dated tag (`debian:trixie-20260701`) or a digest pin if you need reproducibility. Validation happens in the host-side `claude-container` script, so it doesn't apply if you invoke `podman build` directly.

### GitHub Token Wiring

Design principle (v4+, `jj1xgo/claude-container#24`): **keep always-available (exported) privilege minimal; put broad privilege behind an explicit-action wall; be honest in the docs about what risk remains.** Tokens for writing to GitHub (via `gh` CLI or MCP) all live under one generic secrets directory (`SECRETS_DIR`).

| Slot | Location | Exported | Intended use / recommended scope |
|---|---|---|---|
| Main PAT | `SECRETS_DIR` root (e.g. `GITHUB_MAIN_PAT`) | No | push, PR review, release creation, etc. Place broad privilege here (e.g. `Contents: write`). Never appears as an env var value — read it explicitly inside the container, e.g. `GH_TOKEN=$(cat "$GITHUB_MAIN_PAT_FILE") gh ...` |
| MCP / issues-only PAT | `SECRETS_DIR/export/` (e.g. `GITHUB_MCP_PAT`) | Yes | The GitHub official MCP server, and issue-checking hooks. **Recommend an issues-scoped token** (see risk note below) |

**Important**: "where you place `.claude-container.d/env`" and "which repository you select under the PAT's `Repository access`" are two different things. The former is the project that **uses** the token (e.g. myproject); the latter is the repository you're **writing to** (e.g. claude-container). To let myproject write issues to claude-container, place `.claude-container.d/env` inside myproject and select `claude-container` under `Repository access` — not the project that's doing the writing.

Fine-grained PATs apply one permission set uniformly to every repository selected under a single token (you cannot grant different permissions to different repositories within the same token). So if you want "broader permissions on your own repository, Issues-only elsewhere," split tokens by use case as in the table above. See the "What Works and What Doesn't" quick reference below for the full picture of availability and permissions by operation type.

1. Create a token under GitHub Settings → Developer settings → Personal access tokens → Fine-grained tokens. **Do not use a classic PAT** — even its narrowest write scope (`repo`) grants read/write on all your repositories, which is too much blast radius for a leaked token. Configure it according to your use case:
   - Repository access: `Only select repositories` → only the repositories you're writing to (note: if you select more than one, the permissions below apply to all of them uniformly)
   - Repository permissions: grant only the minimum needed. For the MCP/issues token, `Issues: Read and write` alone is recommended. Adding `Pull requests: Read and write` to the main PAT lets it review PRs on your own repo; adding `Contents: write` lets it push, merge PRs, and create releases from inside the container (push, merge, and release creation stay host-side as long as `Contents: write` is withheld)
   - Expiration: 90 days or less recommended
2. Create a directory on the host (e.g. `~/.config/claude-container/secrets.d/<project>`) and `chmod 700` it. **The filename of each file placed inside becomes the environment variable name inside the container — but only under `export/`; files at the root are never exported.** Names not matching `^[A-Za-z_][A-Za-z0-9_]*$` are skipped with a WARNING at startup. `chmod 600` each file; its contents should be a single-line token string (newlines are stripped automatically, so multi-line values get concatenated — not supported). Each file must be a regular file — since only this directory itself is mounted into the container, a symlink pointing outside it cannot be resolved inside the container and is **silently skipped with no warning** (to reuse an existing token file, copy its value instead of symlinking)
3. Place the main PAT at the `SECRETS_DIR` root (e.g. `SECRETS_DIR/GITHUB_MAIN_PAT`). Place the MCP/issues PAT under `SECRETS_DIR/export/` (`chmod 700` that directory too)
4. In the target project's `.claude-container.d/env`, set `SECRETS_DIR=~/.config/claude-container/secrets.d/<project>`. `.claude-container.d/env` is gitignored (it may hold host-specific paths), so it's never committed in the first place
5. Startup aborts (fail-closed) if the directory doesn't exist. A warning is printed if the directory isn't `700` or a file inside isn't `600`

Tokens are only ever files on the host — never passed via the container's `environment:` (so they don't show up in `podman inspect`, etc.). Only the main PAT's *path* is exported, as `GITHUB_MAIN_PAT_FILE` — its value never is. Only tokens under `export/` are exported by value, as an environment variable named after the file. **If the name collides with one already present in the environment (e.g. `PATH`), the existing value is left untouched and a warning is printed instead.**

This is a generic environment-variable-injection mechanism — it isn't limited to GitHub tokens. That said, anything you bring in this way is readable by every process inside the container (Claude itself, hooks, any npm script), so only bring in the minimum set of secrets a given project actually needs. **Placing a file named `GH_TOKEN`/`GITHUB_TOKEN` under `export/` resurrects `gh`'s ambient authentication** — this runs counter to the design intent here, so avoid it unless you understand you're deliberately opting back in (running `gh auth login` inside the container has the same effect and is likewise discouraged).

**Checking configured scope**: **There is currently no way to mechanically retrieve the full list of repositories a fine-grained PAT covers.** GitHub itself has no API that lists a token's accessible repositories at once for personal-account tokens (the equivalent endpoint, `GET /orgs/{org}/personal-access-tokens/{pat_id}/repositories`, is organization-scoped and GitHub-App-only — it doesn't apply to PATs on personal accounts), and this project doesn't track the target repositories either, to avoid drifting out of sync with PAT config changes. So you have to check reachability per repository instead: run `GH_TOKEN=$(cat <token-file>) gh api /repos/<owner>/<repo>` — but the 200/404 result is only meaningful **for private repositories** (200 = in scope, 404 = out of scope). **This does not work for public repositories**: GitHub returns public repository metadata (`GET /repos/{owner}/{repo}` and its `permissions` field) with 200 regardless of the token's `Repository access` setting, so for a public repo neither reachability nor the `permissions` value is evidence of actual scope (verified empirically; see `jj1xgo/claude-container#13`). To check effective scope on a public repository, either attempt a real write operation (e.g. `gh issue create`) or check the `Repository access` list directly in the PAT settings UI. The source of truth for scope always remains the PAT's `Repository access` setting.

**Rotating a token**: When it's nearing expiration, regenerate it on GitHub's side and overwrite the contents of the corresponding file with the new string. This is a runtime mount, not baked in at build time, so no rebuild (`-b`) is needed — the new contents are picked up on the next launch.

**Note**: the startup check only verifies the file exists and its permissions — it does not validate whether the token itself has expired. A container with an expired token still starts normally; the failure only surfaces the first time `gh` actually calls the GitHub API. Keep track of the `Expiration` you set so this doesn't go unnoticed.

**Recipe: using the GitHub official MCP server**: to talk to GitHub via MCP instead of the `gh` CLI, configure as follows.

1. Add `api.githubcopilot.com` to the target project's `.claude-container.d/allowed-domains.txt` (baked in at build time, so requires a `-b` rebuild)
2. Place a PAT file under `SECRETS_DIR/export/` (e.g. named `GITHUB_MCP_PAT`). **Recommend an issues-scoped token** — the MCP server's tool surface includes write tools for push, PR merge, release creation, etc., and a broadly-scoped token makes them live
3. In the target project's `.mcp.json` (Claude Code expands `${VAR}` from the environment):
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

The GitHub official remote MCP server's default auth is OAuth (browser login), which a headless container can't do, so passing a PAT via the `Authorization` header is the practical option here. Note that hooks and other shell-based automation can't call an MCP server (MCP is a tool Claude uses, not something shell can invoke directly), so the bundled `gh` CLI stays in the image even after adopting MCP.

**Defense in depth (`permissions.deny`)**: even with a scoped MCP token, guard against a future switch to a broader one by adding a `permissions.deny` for the write-capable MCP tools in the target project's `.claude/settings.json`:
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
The primary defense is token scope (an issues-only token gets a 403 from the server on write tools). This deny list is the secondary layer, and it's fail-open with respect to future MCP tool additions (a newly added tool isn't automatically blocked). Leave issue-related tools (`issue_write`, `add_issue_comment`, and the read/list/search tools) out of the deny list so they keep working.

**Migrating from v3 or earlier**: `GH_TOKEN_FILE`, `GH_TOKEN_SECONDARY_FILE`, and `SECRETS_DIR/noexport/` were removed in v4 (no backward-compat aliases).

| Old | New |
|---|---|
| `GH_TOKEN_FILE` | `SECRETS_DIR` root (e.g. `GITHUB_MAIN_PAT`) |
| `GH_TOKEN_SECONDARY_FILE` | `SECRETS_DIR/export/` (e.g. `GITHUB_MCP_PAT`) |
| `SECRETS_DIR/noexport/GIT_PUSH_TOKEN` | `SECRETS_DIR/GITHUB_MAIN_PAT` (merged into the push/PR token) |

If a legacy variable is still set, startup aborts fail-closed and prints the migration steps above. Before deleting or moving the underlying file, confirm no other project depends on it (deletion itself is out of scope for this migration — keep the file until that's confirmed).

**Recipe: enabling `git push` (`SECRETS_DIR/GITHUB_MAIN_PAT`)**: by default, `push` doesn't work among git's remote operations (see "What Works and What Doesn't" below). Granting the main PAT `Contents: write` enables it.

1. Create a Fine-grained PAT on GitHub. Limit Repository access to only the repository you're pushing to, and grant `Contents: Read and write` under Repository permissions (`push` requires `Contents: write`). Pairing this with GitHub-side branch protection (required reviews, no force-push) is recommended
2. Save the token string to a file named `SECRETS_DIR/GITHUB_MAIN_PAT` (root, not exported) and `chmod 600` it
3. Set `SECRETS_DIR=...` in the target project's `.claude-container.d/env` (no extra setup needed if it's already configured for another purpose)
4. Requires a `-b` rebuild, since it involves a `Dockerfile.claude` change

On launch, `entrypoint.sh` detects `SECRETS_DIR/GITHUB_MAIN_PAT` and automatically sets `GIT_ASKPASS` (the token's value itself is never exported — only its path, as `GITHUB_MAIN_PAT_FILE`). From then on, `git push` to the target repository (**HTTPS remotes only** — this does not work for SSH remotes) goes through without manual intervention, since `git-askpass.sh` reads the token from the file just in time on each prompt. `git-askpass.sh` is fail-closed: it only answers prompts addressed to github.com, and refuses any other host or unexpected prompt.

Note the side effect: this token also enables fetch/pull on private repositories (since it implies `Contents: Read`). The same `Contents: write` token can also be used from the `gh` CLI, e.g. `GH_TOKEN=$(cat "$GITHUB_MAIN_PAT_FILE") gh pr merge ...` — so PR merges, not just pushes, become "possible but never silent" (they require the same explicit-read step) once this is configured.

When `GITHUB_MAIN_PAT` is detected, `entrypoint.sh` also resets `credential.helper` to empty via `GIT_CONFIG_*` environment variables. This prevents a host gitconfig mounted via `GITCONFIG_FILE` (below) that sets `credential.helper = store` (or similar) from persisting the token `git-askpass.sh` reads just-in-time into `~/.git-credentials` in plaintext (the mounted `~/.gitconfig` is read-only, so `git config --global` can't override it — `GIT_CONFIG_*` environment variables, applied after all config files, are the only way to do this).

**Force-push protection**: `GITHUB_MAIN_PAT` also lets through force-overwrites like `git push --force` from inside the container, so a first line of defense is adding `Bash(git push --force:*)` to `permissions.deny` in the target project's `.claude/settings.json`. That deny rule matches by command-string prefix, though, so it lets through the flag-suffixed form (`git push origin master --force`), `git -C <path> push --force`, and `+refspec` syntax (e.g. `git push origin +feature:main`) — a known gap. `--force-with-lease` doesn't start with `--force`, so it needs its own rule (`Bash(git push --force-with-lease:*)`). Closing every gap with deny rules alone gets unwieldy, so pair it with a documented rule ("force push only after explicit user approval") in CLAUDE.md or similar as a second line of defense (a finding from real-world verification in downstream projects).

**Committing from inside the container (`GITCONFIG_FILE`)**: Even if you've set `git config --global user.name`/`user.email` on the host, it isn't reflected inside the container by default, so `git commit` fails with `Author identity unknown`. Fix it by adding this to `.claude-container.d/env`:

```
GITCONFIG_FILE=~/.gitconfig
```

- If unset, behavior is unchanged (`git commit` just fails with `Author identity unknown`; nothing else is affected)
- If set, startup aborts with an error if the file doesn't exist (fail-closed) — this avoids a bind-mount quirk where a nonexistent source path gets silently created as an empty directory on the host
- The mount is read-only, so `git config --global` cannot be used to edit it from inside the container. Always edit it on the host (it's a runtime mount, so no `-b` rebuild is needed — the next launch picks up the change)
- A `credential.helper` or `include.path` entry pointing at a host-specific file doesn't affect `git commit` itself (a missing include is silently ignored, and a missing credential helper only warns during authenticated operations). If that's a concern, point `GITCONFIG_FILE` at a dedicated file containing only `user.name`/`user.email` instead
- If `GITCONFIG_FILE` doesn't seem to take effect, check whether `/workspace` (the target project you launched) has its own `.git/config` with `user.name`/`user.email` set. Git's config precedence (local > global) means the target project's local setting wins over the mounted `~/.gitconfig` (which acts as the global config)

**Always create language-runtime artifacts like venvs inside the container, not on the host.** Running `python3 -m venv` on the host inside the target project directory bakes the host's absolute path and username into the generated scripts' shebangs (e.g. `venv/bin/pip`'s first line becomes `/home/alice/myproject/venv/bin/python3`). Since the same directory is mounted inside the container at `/workspace` under the `node` user, that path doesn't resolve and shebang-based execution (`./venv/bin/djlint`, etc.) fails (invoke the venv's own python3 as a module instead, e.g. `venv/bin/python3 -m djlint` — plain `python3` is the system interpreter and won't see the venv's site-packages). Create the venv from inside a running container instead.

### Adding MCP Servers

`.mcp.json` isn't a claude-container mechanism — it's a standard Claude Code feature that auto-loads a `.mcp.json` at the project root (`/workspace`) as a project-scoped server. Depending on its type (http or stdio), the following range can be added **entirely from the target project's own configuration, with no change to claude-container itself**.

**http/sse type** (servers that connect directly to a remote endpoint — e.g. the GitHub official MCP server; see the "Recipe: using the GitHub official MCP server" subsection under "GitHub Token Wiring" above for a concrete example):

1. Place `.mcp.json` at the target project's root (Claude Code loads it automatically)
2. If authentication is needed, place a token file under `SECRETS_DIR/export/` under any name (see "GitHub Token Wiring" above) and reference it from `.mcp.json` as `${variable-name}`
3. Add the target domain to `.claude-container.d/allowed-domains.txt` (baked in at build time, so requires a `-b` rebuild)

**stdio type** (servers that run as a command inside the container) cannot be added unilaterally. `entrypoint.sh` audits `/workspace/.mcp.json` at startup; when it detects a server with a `command` field, it prints the server name and command and requires interactive (TTY) confirmation. If confirmation can't be obtained (non-interactive launch, or declined), startup aborts (fail-closed).

Why this confirmation exists: unlike http-type servers, stdio-type code can be bundled directly in the repository and executed without any network fetch (e.g. via `npx`), so it doesn't pass through the existing firewall/rebuild wall. Since Claude Code's own MCP approval prompt doesn't function under `--dangerously-skip-permissions` (see "Security Model" below), this confirmation is the only remaining wall. **There is deliberately no environment-variable opt-out**: `.claude-container.d/env` exports every key except protected (`readonly`) ones, so an opt-out variable could be set by the untrusted repository itself, making it meaningless as a gate against a malicious one.

If you do need a stdio-type server, prefer baking it in via `.claude-container.d/packages.txt` or a host-side install + bind mount (e.g. `EXTRA_MOUNT`), rather than runtime fetching via `npx` (which fetches unverified code over the network on every session start). **The `packages.txt` path can't pin a version** (`pkg=version` pins are rejected by allowlist validation) — use the bind mount path if you need a pinned version. Relatedly, don't add npm registries (e.g. `registry.npmjs.org`) to `allowed-domains.txt` — doing so would make `npx`-based runtime fetching work, which not only forces the confirmation above on every session but also removes any check on the code being fetched.

**Skipping the confirmation via TOFU (Trust On First Use)** (claude-container#28): answering `y` makes the `claude-container` script record a hash of the approved stdio server definitions on the host, under `~/.local/state/claude-container/mcp-approvals/<project>` (not inside `.mcp.json` or the container — the point is to keep it somewhere the container itself can't alter). On subsequent launches, confirmation is skipped automatically as long as the stdio server definitions in `.mcp.json` still match that record; any change to the definitions triggers a fresh confirmation. Records are per-project; `--clean <directory>` removes the one for that project, and `--clean` with no argument removes all of them.

Note that registering a server via `claude mcp add` at local/user scope (`~/.claude.json`) is outside this gate's scope — since the repository doesn't control that file, it doesn't fall under the "malicious repository's first launch" threat model, and is left to each project's own management.

**Recipe: using the Codex CLI as a second-opinion MCP server** (a concrete `stdio`-type example; internal ops issue):

1. Write the desired Codex version (e.g. `0.46.0`) or `latest` to the target project's `.claude-container.d/codex-version.txt` (see "Target Project Configuration" above). npm is required, so also set `node-version.txt`.
2. Add `chatgpt.com` to the target project's `.claude-container.d/allowed-domains.txt`. Codex using ChatGPT-account auth (`auth.json`) hardcodes its API base URL to `https://chatgpt.com/backend-api/` (see [openai/codex](https://github.com/openai/codex)'s `CHATGPT_CODEX_BASE_URL` in `codex-rs/model-provider-info/src/lib.rs`); without this, the egress firewall blocks the calls.
3. Set up a dedicated Codex credentials directory on the host and seed it once with `~/.codex/auth.json` (from a host where you've already run `codex login`). **Do not point `CODEX_DIR` at your real `~/.codex`** — the rw mount needed for auth.json's refresh write-back means a shared real directory lets container-side code rewrite `config.toml` (e.g. its `notify` hook), creating a path to arbitrary command execution on the host next time you run Codex there (see the corresponding comment in `.claude-container.d/env.example`):
   ```
   mkdir -p -m 700 ~/.codex-container
   cp ~/.codex/auth.json ~/.codex-container/auth.json
   chmod 600 ~/.codex-container/auth.json
   ```
4. Set `CODEX_DIR=~/.codex-container` in the target project's `.claude-container.d/env` (no `-b` needed, runtime mount).
5. Add the following to the target project's `.mcp.json` (`codex mcp-server` is stdio-type, so the confirmation-on-first-use flow above applies):
   ```json
   {
     "mcpServers": {
       "codex": {
         "command": "codex",
         "args": ["mcp-server"]
       }
     }
   }
   ```
6. Requires a `-b` rebuild (`codex-version.txt`/`allowed-domains.txt` are both build-time settings).

**Operational notes**: MCP-based calls require Claude Code to pass `cwd` explicitly; forgetting to do so risks picking up an unintended `AGENTS.md` ([openai/codex#12128](https://github.com/openai/codex/issues/12128)) — always anchor consultations at `/workspace`. There's also a known issue report around the auth.json refresh flow ([openai/codex#15502](https://github.com/openai/codex/issues/15502)); treat this area as not fully battle-tested yet.

### Architecture

The main files work together:

- **`claude-container`** (bash) — Entry point. Resolves absolute paths, then computes `PROJECT_NAME` from the target project's directory basename (sanitized) plus the first 8 characters of a sha256 hash of its absolute path (e.g. `myproject-3f2a9c1b`). This separates the image name (`localhost/<PROJECT_NAME>_claude-auth-workspace`) and the staged build context (`.build-context/<PROJECT_NAME>/`) per project, and `-p "$PROJECT_NAME"` is passed to `podman compose` accordingly. Previously the image name and staging path were fixed regardless of the target project, so interleaving builds across different projects would silently overwrite each other's image and staged context. Reads `KEY=VALUE` lines from `.claude-container.d/env` with a literal parser (no `source`, quoting, or shell expansion), auto-detects `TZ`, sets `CONTEXT` / `CLAUDE_CONTAINER_DIR`, and delegates to `podman compose run`. When `-b` is passed, `podman compose build` runs as a separate step before `run` — `run --build` would fall back to the existing stale image when the build fails (fail-open), whereas the separate build step aborts the launch on failure (fail-closed). Before building, it stages `entrypoint.sh`, `init-firewall.sh`, `git-askpass.sh`, `validate-build-input.sh`, the GitHub meta snapshot (see below), plus the project's `.claude-container.d/packages.txt` / `requirements.txt` / `allowed-domains.txt` (or claude-container's bundled defaults if absent) and `node-version.txt` / `codex-version.txt` / `allowed-ports.txt` (an empty file is synthesized on the fly if absent — unlike the other three, none of these has a bundled default and none warns) into that project's `BUILD_CONTEXT_DIR` (only when `-b` is passed, or when the image hasn't been built yet). `--clean <directory>` removes only that project's image, network, and build context; `--clean` (no directory) scans for all existing claude-container images and removes every project's worth (the legacy shared image `localhost/claude-container_claude-auth-workspace` matches the same naming pattern, so upgrading from an older version just requires running `--clean` once to reclaim it).
- **`compose.yml`** — Defines the `claude-auth-workspace` service. The build context is `${BUILD_CONTEXT_DIR}` (the staged directory above); the Dockerfile is `${CLAUDE_CONTAINER_DIR}/Dockerfile.claude`. Mounts `~/.claude.json`, `~/.claude/`, the target workspace (`/workspace`), and `/etc/localtime`. Uses `userns_mode: keep-id` to match the host user's UID/GID. Adds `NET_ADMIN`/`NET_RAW` capabilities via `cap_add` so `init-firewall.sh` can configure iptables rules inside the container's network namespace (under rootless podman + `userns_mode: keep-id`, these also land in the non-root `node` user's ambient set and are inherited by every child process — stripped by `Dockerfile.claude`'s `ENTRYPOINT` below; see "Security Model"). Sets `net.ipv6.conf.{all,default}.disable_ipv6=1` via `sysctls` to disable IPv6 at the kernel level (see below). When `CODEX_DIR` is set, mounts the Codex CLI credentials directory rw (unlike the other opt-in mounts, no `:ro` — needed for auth.json's token refresh write-back; see the Codex recipe under "Adding MCP Servers" above).
- **`Dockerfile.claude`** — Based on `debian:stable` by default (overridable via `.claude-container.d/base-image.txt`, see "Target Project Configuration" above; `FROM` is evaluated before `COPY`, so the file can't be read directly — it's passed in via `ARG BASE_IMAGE`). Installs `ca-certificates` via HTTP first, then rewrites every apt source URI (not a hardcoded hostname, so it doesn't silently no-op against a different mirror) to HTTPS before installing remaining packages. Right after the fixed apt layer, a build-time assertion (added alongside base-image configurability) fails the build, fail-closed, if `setpriv`/`tini` are missing, `setpriv` doesn't accept `--ambient-caps`/`--inh-caps`, or an `http://` apt source survived the rewrite — so the security boundary's foundation can't silently break while the build still succeeds. Claude Code is installed via the official native installer (`curl -fsSL https://claude.ai/install.sh | bash`). Runs as the non-root `node` user (UID 1000, created explicitly), executing `CMD ["/usr/local/bin/entrypoint.sh"]` (see next item; placed as a boundary asset in the root-owned `/usr/local/bin`, so `node` cannot alter it). Switched from `node:24` (~1.1 GB) because the native installer only requires glibc — no runtime Node.js needed. Full (not slim) Debian is used to avoid extra setup steps that slim requires. `ENTRYPOINT` is `setpriv --ambient-caps=-all --inh-caps=-all /usr/bin/tini --`, which strips ambient/inheritable capabilities from the whole process tree before starting `tini` (`setpriv` execs, so it doesn't linger; `tini` stays at PID1). This neutralizes `compose.yml`'s `cap_add` landing in the non-root user's ambient set (see previous item), leaving `sudo`-invoked, root-run `init-firewall.sh` (via the unaffected bounding set) as the sole consumer of `NET_ADMIN`/`NET_RAW`. Putting `tini` at PID1: with claude itself as PID1, children reparented to PID1 (e.g. the firewall refresh loop's sudo helpers) were never reaped and accumulated as zombies, and when claude wedged on exit (2026-07-02: a host-kernel workqueue Oops left an unkillable D-state thread), the zombie PID1 could not be signalled at all (`crun kill ... failed` / "No such process") and `podman stop` could not reclaim the container. tini keeps reaping and `podman stop` working (it cannot fix a kernel-side wedge itself). `tini` is kept out of `packages.txt` and installed in the fixed apt layer instead, so a project's `.claude-container.d/packages.txt` can't silently drop it. Right after the `node-version.txt` block, a layer using the same opt-in convention installs the Codex CLI (`@openai/codex`) via npm when `codex-version.txt` specifies a version (aborts the build with an error if npm is missing; internal ops issue). Ingesting `packages.txt`/`requirements.txt` gets the same class of fail-closed build-time check — `validate-build-input.sh` runs allowlist validation before `apt-get`/`pip3` — so, like the setpriv/tini assertion, the security boundary's foundation can't silently break while the build still succeeds (see "Target Project Configuration" above).
- **`entrypoint.sh`** — The container's `CMD` (PID1 is the `tini` above; this script and the claude process it execs into run as its child). Applies the egress firewall via `init-firewall.sh` at startup (aborts launch on failure), starts a background domain re-resolution loop (~15s interval, see next item), then launches `claude --dangerously-skip-permissions`. Also auto-fixes host-specific paths under `~/.claude/plugins/` to their in-container equivalents, and audits `/workspace/.mcp.json`, requiring interactive confirmation if a stdio-type MCP server is detected (fail-closed; see "Adding MCP Servers" above).
- **`init-firewall.sh`** — Egress firewall script run as root (via sudo) at container startup. A port of the same-named script from Anthropic's official devcontainer: it blocks all outbound traffic except allowed destinations (deny-by-default iptables rules). Only the endpoints Claude Code needs (api.anthropic.com, GitHub, etc.) and the project's `allowed-domains.txt` are allowed. Rules for allowed domains (GitHub CIDRs and tagged domain rules) are further restricted to the TCP ports listed in `allowed-ports.txt` (default `443,22`; `jj1xgo/claude-container#31`) — this restriction applies only to allowed-domain rules, not to DNS (port 53, resolver-scoped) or the host-network rule (scoped to the gateway's single IP, not its whole `/24`; each is narrowed for its own separate reason). GitHub IP ranges are never fetched live at startup — only the build-time snapshot is read (see "GitHub Meta Snapshot" below). After setup it self-verifies that example.com is **unreachable**, api.github.com / api.anthropic.com **are** reachable, and a non-allowed port on an allowed domain (api.github.com:80) is **unreachable** (the GitHub checks are quota-free TCP connects), and refuses to start the container on failure (fail-closed). The one exception: if an allowed domain (including one from `allowed-domains.txt`) no longer exists at all (NXDOMAIN), that's logged as a warning and startup proceeds — only transient resolution failures still trip fail-closed. IPv6 is primarily disabled via `compose.yml`'s `sysctls`; as a fallback for environments where that doesn't take effect, this script also attempts to write `/proc/sys/net/ipv6/conf/*/disable_ipv6` itself (non-fatal if it fails — logs a warning and continues). Either way, the existing `ip6tables` IPv6 blackhole (the allowlist only resolves A records) remains the last line of defense. Allowed domains' IPs are re-resolved roughly every 15s by a background loop `entrypoint.sh` starts (`init-firewall.sh --refresh-domains`), which diff-adds newly seen IPs and individually removes ones unseen for about 3 minutes — this keeps up with CDNs that rotate IPs on short TTLs, without ever flushing the whole chain (so no gap where new connections fail during a refresh).
- **`validate-build-input.sh`** — POSIX sh script that normalizes and validates `packages.txt`/`requirements.txt`. Called from three places — build time (the `RUN` in `Dockerfile.claude`), pre-launch diagnosis (`--check`), and tests (`test-build.sh`) — so the validation logic can't drift by being duplicated across them (`claude-container#34`). Its only job is normalization and validation; it never installs anything or touches the network.
- **`packages.txt`** / **`requirements.txt`** / **`allowed-domains.txt`** — claude-container's bundled default apt/pip package and allowed-domain lists (fallback values). Projects override these via `.claude-container.d/` (see "Target Project Configuration" above). `node-version.txt`/`allowed-ports.txt` have no such bundled default — if the project doesn't provide one, `claude-container` synthesizes an empty file in the build context on the fly (meaning "no Node.js install" for the former, and "let `init-firewall.sh` itself apply its default `443,22`" for the latter; neither warns). `codex-version.txt` follows the same convention (no Codex CLI install, no warning).

#### GitHub Meta Snapshot

The GitHub IP ranges used by `init-firewall.sh`'s allowlist come from `https://api.github.com/meta`. To avoid the unauthenticated GitHub API rate limit (60 req/h/IP), the fetch happens in exactly one place — while `claude-container` stages the build context (at most one request per `-b`) — and `Dockerfile.claude` bakes the result into the image. There's no live fetch on container startup, so restarting the container never consumes the rate limit. If the fetch fails, (1) this project's previously staged snapshot (still in `.build-context/<PROJECT_NAME>/`) is reused with a warning, or (2) failing that, another project's most recent snapshot is reused with a warning (GitHub's IP ranges change infrequently enough that this is fine in practice); the build only aborts if neither exists.

### Modifying the Image

Edit `Dockerfile.claude` and rebuild with `./claude-container -b /path/to/project`. The `-b` flag re-fetches the GitHub meta snapshot (see above) and passes a `CACHEBUST` build arg (current epoch seconds) that busts the install-layer cache on every run, so `install.sh` always re-executes and fetches the latest Claude Code. Layers above the install step (apt packages etc.) are still served from cache, keeping rebuilds fast. Pin `CLAUDE_CODE_VERSION` in `compose.yml` if reproducibility matters.

Changes to the package lists, allowed domains (`allowed-domains.txt`), allowed ports (`allowed-ports.txt`), Node.js version (`node-version.txt`), or the base image (`base-image.txt`) under `.claude-container.d/` also require a `-b` rebuild to take effect. So do changes to scripts staged into the build context — `entrypoint.sh`, `init-firewall.sh`, `git-askpass.sh`, `validate-build-input.sh`, or `Dockerfile.claude` itself (see "Architecture" above).

`.build-context/` is a generated build context under the claude-container repo (git-ignored), split into a `.build-context/<PROJECT_NAME>/` subdirectory per project. `./claude-container --clean /path/to/project` removes just that project's; `./claude-container --clean` (no directory) removes all of them.

Claude Code's auto-updater is disabled via `DISABLE_AUTOUPDATER: "1"` in `compose.yml`. Since containers run with `--rm`, any updates downloaded at runtime are discarded on exit anyway — use `-b` to rebuild the image when you want a newer version.

### Persistence Across Container Runs

Containers start with `--rm`, so internal state is lost on exit. However, the following always-on bind mounts are **preserved across restarts** (opt-in mounts such as `EXTRA_MOUNT`/`SHARED_MOUNT`/`SECRETS_DIR` persist the same way as long as you keep the host-side path in place, but they're omitted here since they're optional — see the "Environment Variables" section for the full list):

| Container path | Host path | Contents |
|---|---|---|
| `/home/node/.claude/` | `~/.claude/` | Claude memory, config, session history |
| `/home/node/.claude.json` | `~/.claude.json` | Claude credentials |
| `/workspace/` | Directory specified at launch | Target project |

### What Works and What Doesn't (git / gh / PAT / hook quick reference)

`git` and the `gh` CLI inside the container have completely independent authentication systems. `git push` fails not because of insufficient permissions, but because a credential helper is deliberately left unwired; `gh` is unauthenticated by default (no `GH_TOKEN` or similar ambient export). Both only authenticate once you point them at a token file under `SECRETS_DIR` — the main PAT via an explicit read, the MCP/issues PAT via its exported value.

**Authentication path and availability by operation type**

| Operation | Authentication path | Availability inside the container |
|---|---|---|
| git local operations (`commit` / `log` / `diff` / `branch` / `merge`, etc.) | None required (`commit` alone needs `user.name`/`user.email` via `GITCONFIG_FILE`, as above) | Works |
| git remote operations (`push` / `pull` / `fetch`) | git credential helper (**not wired** by default. Wired via `GIT_ASKPASS` only when `SECRETS_DIR/GITHUB_MAIN_PAT` is set) | By default, **push does not work**. **fetch/pull on public repositories works** (no auth required; private repos' fetch/pull don't work). Setting `SECRETS_DIR/GITHUB_MAIN_PAT` (above) enables push to the target repository (and, as a side effect, fetch/pull on private repositories with the same token) |
| `gh` CLI (bare) | None | **Unauthenticated and fails by default** (the normal v4+ state) |
| `gh` CLI (main PAT, explicit read) | `GH_TOKEN=$(cat "$GITHUB_MAIN_PAT_FILE") gh ...` | Works within the main PAT's permissions and repository scope |
| `gh` CLI (MCP/issues PAT) | `GH_TOKEN="$GITHUB_MCP_PAT" gh ...` (prefixing the ambient-exported value) | Works within the MCP/issues PAT's permissions (usually Issues only) |
| MCP (GitHub official server) | `${GITHUB_MCP_PAT}` (`.mcp.json`'s Authorization header, via the exported value) | Same as above |

**Main PAT / MCP-issues PAT reference table**

| Item | Main PAT (`SECRETS_DIR` root) | MCP/issues PAT (`SECRETS_DIR/export/`) |
|---|---|---|
| Intended use | push, PR review, release creation, etc. — broad operations on your main target repository | Issue communication and MCP-driven operations (including cross-repo) |
| Exported | No (only the path, as `GITHUB_MAIN_PAT_FILE`) | Yes (filename becomes the env var name, with its value) |
| Permissions generally fine to grant | Combine `Issues`/`Pull requests`/`Contents` per use case (understand that including `Contents: write` makes push/approve/merge possible via an explicit read) | `Issues: Read and write` only |
| Permissions it should not have | — (non-export makes the explicit-read step a structural wall) | `Pull requests: write`, `Contents: write` (these show up as live MCP write tools unless the token is scoped tightly) |
| Setup and scope checking | See "GitHub Token Wiring" above | Same |

**Reading and writing the host's Claude Code settings (`~/.claude`)**

| Target | Inside the container |
|---|---|
| The 11 user-scope settings items: `hooks/` `skills/` `plugins/` `commands/` `agents/` `workflows/` `rules/` `output-styles/` `settings.json` `CLAUDE.md` `statusline.sh` | Readable, **not writable** (`:ro` overlay mounts. Create, update or delete them, run `/plugin` install/update, and change settings saved there on the host instead. Host-side updates become visible after a container restart) |
| State such as credentials (`.credentials.json`), transcripts (`projects/`), auto memory (`projects/<p>/memory/`), `history.jsonl` | Read/write (unchanged) |
| Project-scope settings (`/workspace/.claude/` settings, skills, agents, commands, rules, CLAUDE.md, and `.mcp.json`) | Read/write (unchanged; see "Security Model" for how the host treats them) |

**Additional restrictions via hooks**

This protection ships as `examples/hooks/block-pr-approve.sh` in this repository, but it isn't wired into the product itself. To apply it, wire it into a target project's own `.claude/settings.json` (see `examples/hooks/README.md` for the wiring example and regression tests). Forks inherit the file as-is, but it does nothing until wired.

| Mechanism | Blocks | Allows |
|---|---|---|
| PreToolUse hook `examples/hooks/block-pr-approve.sh` | `gh pr review --approve` (and `-a`, including short-option clusters containing `a`) / `gh api …/pulls/<N>/reviews` with `event=APPROVE` (including via quoted strings or heredoc bodies) | `--comment`, `--request-changes`, and other PR operations, plus `gh` commands in general |
| `permissions.deny` | (currently unused — this protection's only mechanism is the hook above) | — |

- **Division of labor**: `permissions.deny` suits cases that can be blocked outright by a static prefix/glob pattern. This case needs context-dependent judgment ("block `--approve` under `gh pr review` but allow `--comment`"; "detect `event=APPROVE` even inside a JSON body or heredoc"), which a deny glob would either over-block or fail to catch — hence the hook.
- **Known false positives/negatives**: Residual false positive (safe direction, accepted) = the executed command is genuinely `gh api` and its heredoc body quotes both `pulls/N/reviews` and `event=APPROVE`, or a multi-line double-quoted string contains an approval string. Residual false negative (outside the threat model) = deliberate obfuscation that plants `<<X` inside a quoted string to misfire heredoc stripping. The threat model is "prevent Claude from autonomously approving by accident" — deliberate obfuscation is explicitly out of scope.
- **See also**: risk details in "Security Model" below; hook implementation, wiring example, and regression tests in `examples/hooks/README.md`.

### Security Model

Claude runs with `--dangerously-skip-permissions`, meaning it operates without tool-use confirmation prompts. The container boundary is the guardrail — Claude has full read/write access to the mounted workspace, `/data`, and `/shared`. Do not mount directories containing sensitive data outside the intended project scope. `SHARED_MOUNT` (`/shared`) is a shared area where every container that has the same host path configured gets full rw access — only set it across projects that trust each other.

Network access is restricted by default via the `init-firewall.sh` egress allowlist. Outbound traffic to anything other than the endpoints Claude Code needs (Anthropic API, GitHub, etc.) and the domains listed in `.claude-container.d/allowed-domains.txt` is blocked, preventing malicious pip packages or prompt injection from exfiltrating credentials (`~/.claude.json`) or source code to arbitrary hosts. If you need unrestricted network access, set `CLAUDE_CONTAINER_NO_FIREWALL=1` in `.claude-container.d/env` (at your own risk).

This guardrail only holds if Claude (and its children) cannot rewrite the allowlist itself. `compose.yml`'s `cap_add` (`NET_ADMIN`/`NET_RAW`) lands in the non-root user's ambient set under rootless podman and is inherited by every child process — without mitigation, Claude could operate iptables directly without going through sudo (and `CAP_NET_RAW` alone can bypass netfilter entirely via `AF_PACKET`). `Dockerfile.claude`'s `ENTRYPOINT` (see "Architecture" above) strips these capabilities at container startup, leaving `sudo`-invoked, root-run `init-firewall.sh` as the sole consumer of `NET_ADMIN`/`NET_RAW`. **Residual constraint**: the capability bounding set itself cannot be removed (that requires `CAP_SETPCAP`, which is not granted either), so if a project adds a binary with file capabilities (e.g. `iputils-ping`, `wireshark`) via `.claude-container.d/packages.txt`, that specific binary's capability can be restored for its own function (the bundled default `packages.txt` ships no such binary). Processes entering via `podman exec` from the host also bypass `Dockerfile.claude`'s `ENTRYPOINT` and are unaffected by this restriction.

**Residual risks the allowlist cannot prevent**: tunneling over DNS queries, exfiltration to allowed services themselves (e.g. GitHub), and reachability of other sites behind shared CDN IPs. Allowed domains' IPs keep up with rotation via the ~15s background refresh (see Architecture above), but the tens of seconds between a rotation and the next refresh cycle can still see new-connection failures (a large improvement over needing a container restart, but not zero). GitHub IP ranges are fixed at build time, so a container restart does not refresh them — a `-b` rebuild is required instead. Build-time network access (`pip3 install` etc.) is not restricted.

**`packages.txt`/`requirements.txt` build-time injection defenses still have residual risk**: both files go through allowlist validation by `validate-build-input.sh` (see "Target Project Configuration" / "Architecture" above), but because PyPI is open publishing, naming an arbitrary package in `requirements.txt` can still run its sdist's `setup.py` as root at build time (`claude-container#34`) — this path is inherent to the platform. The apt side has no equivalent, since it's limited to packages in configured repositories.

**The claude-in-chrome integration cannot be blocked by the firewall, in principle** (`jj1xgo/claude-container#32`): Claude Code's built-in claude-in-chrome integration (`mcp__claude-in-chrome__*`) doesn't go through `.mcp.json` — it's a native feature, so it's outside the MCP audit gate's scope — and it's reachable and usable from inside the container. Hands-on investigation found that every new TCP connection made when it's used lands on port 443 to `claude.ai`/`api.anthropic.com`, which are domains the egress firewall must allow for Claude Code itself to function — meaning this path piggybacks on the exact thing the firewall is trying to restrict, and can't be closed without removing an allowed domain the tool itself needs. What appears on the host is only Chrome's standard `chrome.debugger` notification ("'claude' started debugging this browser"), which is not prior approval but **after-the-fact notice with an optional cancel** (fail-open — it goes unnoticed unless a human is watching the screen). As a result, code running in the container (including code that may have received a prompt injection) can operate the host's real browser — with its real, logged-in sessions — without any human approval beforehand. This sits **outside** the "the guardrail is the container boundary" premise stated at the top of this section. As a mitigation, you can add `mcp__claude-in-chrome__*` to `permissions.deny` in `.claude/settings.json` — but like the other MCP-related `permissions.deny` entries, this is a **soft gate that code inside the container can rewrite**.

**MCP server approval prompts don't function**: Claude Code's own design shows an approval prompt before using a project-scoped `.mcp.json` server, but we've confirmed empirically that this confirmation doesn't run under `--dangerously-skip-permissions` (the server runs even while `enabledMcpjsonServers` stays empty). A stdio-type server (one that runs a command inside the container) would then execute immediately at session start, with no human or model judgment in between, and would be able to read the container's tokens — so claude-container adds its own interactive confirmation gate in `entrypoint.sh` (see "Adding MCP Servers" above). http/sse-type servers are outside this gate, but their destination is still vetted by the firewall allowlist. **A residual path**: registering a server via `claude mcp add` at local/user scope (`~/.claude.json`) is outside this gate, and could be used to persist access from an already-compromised session.

**`.claude-container.d/env` is an attack surface for untrusted repositories**: since `env` exports every key except protected (`readonly`) ones (see "Environment Variables" above), a security opt-out like `CLAUDE_CONTAINER_NO_FIREWALL=1` takes effect if it's simply present in that project's own `.claude-container.d/env`. Review the contents of `.claude-container.d/env` before launching an untrusted repository.

**`.mcp.json` is the only one that gets an extra gate — because the line is drawn by the severity of the consequence, not by input trustworthiness** (`claude-container#29`): repository-bundled configuration (both `.claude-container.d/env` and `.mcp.json`) is, either way, the operator's responsibility to review before launch — there's no basis for calling one "trusted" and the other "untrusted" when both ship in the same repository. claude-container adds an extra interactive gate only where skipping that review leads to "arbitrary code execution at session start" (i.e. `.mcp.json`'s stdio-type servers). `env` keys don't execute code "at session start" the way a stdio-type server does, but keys tied to runtime name resolution (e.g. `PATH`) can still lead to code execution on the host ([`#44`](https://github.com/jj1xgo/claude-container/issues/44)). That path is outside this gate. Separately, the use of boundary-affecting keys (`EXTRA_MOUNT`, `SHARED_MOUNT`, `SECRETS_DIR`, `GITCONFIG_FILE`, `CODEX_DIR`, etc. — runtime name-resolution keys like `PATH` are not covered by this list) is surfaced at launch time so it can't go unnoticed (`guard_env_boundary_keys()`). This visibility is not fail-closed — the premise that `env` is something the operator writes themselves is unchanged.

To see this visibility in action, write `CLAUDE_CONTAINER_NO_FIREWALL=1` (or `EXTRA_MOUNT`/`SHARED_MOUNT`/`SECRETS_DIR`/`GITCONFIG_FILE`/`CODEX_DIR`) to `.claude-container.d/env` and launch — the value itself is never logged, only the key name.

**Read-only protection of the host's Claude Code settings**: the host's `~/.claude` (based at `CLAUDE_CONFIG_DIR`) is bind-mounted rw into the container (needed to share credentials and transcripts), but the 11 user-scope settings items that the host executes or loads (see the table in "What Works and What Doesn't" above) are overlaid by `compose.yml` with `:ro` bind mounts inside that rw mount, so they cannot be modified from the container **through this mount**. The reason: if a compromised session writes hooks, skills, or plugins there, the host's Claude Code loads and runs them (user-settings hooks are picked up by a file watcher, so even a running host session is affected). Because podman would create sub-uid-owned stubs on the host when a mount target is missing, `claude-container` creates any missing item empty, as your user, right before launch (after all guards and MCP approval) and reports it with `INFO:` (`--check` reports `[WARN]` instead of creating). If any of the 11 items is a symlink or has the wrong type (e.g. a file where a directory is expected), the launch aborts. Symlinks are rejected because the `:ro` child mount attaches to the link target while the link itself stays inside the rw parent mount, so deleting and recreating it from the container would replace it with a writable entity (bypassing the protection). **Limits**: (1) the protection covers this mount only; if `/workspace` (the working directory), `EXTRA_MOUNT` or `SHARED_MOUNT` contains `~/.claude` or points at one of the protected items itself, it is writable through that other path, and the launcher prints a `WARNING` (detection is by path containment only; links inside the other mount are not detected). (2) Project-scope settings (`/workspace/.claude/` and `.mcp.json`) are out of scope; once you trust that folder on the host, the host's Claude Code loads them. (3) `~/.claude.json` (trust flags, user-scope MCP registrations), auto memory (`projects/<p>/memory/`), `agent-memory/`, `shell-snapshots/` and `session-env/` are out of scope because Claude Code writes them at runtime; the first three can re-inject instructions into host sessions. (4) If a protected file (`settings.json`, a `CLAUDE.md` import, a dependency read by a hook or plugin) points outside `~/.claude` or into an unprotected area, that target is not protected. (5) The host-side execution path via `PATH` etc. in `.claude-container.d/env` (`#44`) is independent of this protection and remains open. (6) If a host-side tool replaces one of the 11 files by rename, a running container keeps seeing the old file until restart.

If `SECRETS_DIR` (see "GitHub Token Wiring" above) is set, the "exfiltration to allowed services themselves" risk above stops being passive: prompt injection or a malicious package running in the container can read a token (the main PAT as a file, the MCP/issues PAT as an exported env var) and write to GitHub (or elsewhere) within its scope. The mitigation is scoping each fine-grained PAT down (single repository, short expiration), which structurally limits the blast radius to that repository. By design, only tightly-scoped tokens (e.g. issues-only) are exported at all — broad privilege sits behind the non-exported, explicit-read wall instead, which lowers this risk's default (see the design principle in "GitHub Token Wiring"). Since `SECRETS_DIR` is a generic mechanism, this active risk extends to every secret you bring in, not just GitHub tokens (again, bring in only the minimum set a given project actually needs — see above).

If `CODEX_DIR` is set (see the Codex recipe under "Adding MCP Servers" above), code running in the container can read Codex's credentials (`auth.json`, a ChatGPT account access token). Unlike `SECRETS_DIR`, this mount is rw, so container-side code can also write to it — the design uses a dedicated directory (not the real `~/.codex`) precisely to keep that write access from reaching the host's own Codex environment (e.g. `config.toml`'s `notify` hook). Registering Codex as a stdio-type MCP server in `.mcp.json` puts it under the MCP audit gate (TOFU) described above.

If `SECRETS_DIR/GITHUB_MAIN_PAT` (see "Recipe: enabling `git push`" above) has `Contents: write`, the active risk extends to push and PR merges as well: prompt injection or a malicious package could go through the explicit read (`GH_TOKEN=$(cat "$GITHUB_MAIN_PAT_FILE") ...`) to cause unintended commits, pushes, or merges on the target repository. Non-export makes this "never silent," but it's not an absolute wall — any process in the container can read that file path. The mitigation is the same scoping (single repository) combined with GitHub-side branch protection (no force-push, required reviews).

Additional risk if the main PAT grants `Pull requests: Read and write` on your own repository:

- **Larger attack surface**: rewriting other PRs' titles/bodies, spamming review requests, or closing PRs disruptively — similar in kind to issue abuse, but one notch heavier
- **Push/merge still requires `Contents: write`**: merging a PR (`PUT …/pulls/{n}/merge`) requires the `Contents: write` permission; `Pull requests` permission alone cannot perform it. If the main PAT also has `Contents: write`, this wall doesn't apply (see the push section above)
- **Watch for auto-merge bypass**: submitting an approving review (`gh pr review --approve`) only requires `Pull requests: write`, not `Contents: write`. If auto-merge is enabled on the target repo, a malicious approval from the container's token could satisfy a required-review branch protection rule and let GitHub complete the merge on its own. Keep auto-merge disabled (the first wall); the bundled PreToolUse hook (`examples/hooks/block-pr-approve.sh`, if wired) can also mechanically block autonomous approval (the second wall — see "What Works and What Doesn't" above for its scope and limits). Approval via MCP (`mcp__github__pull_request_review_write` etc.) is outside this hook's scope — use the `permissions.deny` from "GitHub Token Wiring" as a separate wall for MCP.

### Podman-specific Notes

- `userns_mode: keep-id` maps the host user's UID/GID into the container. This is a Podman feature — remove it if adapting for Docker.
- `--in-pod false` prevents Podman Compose from wrapping the service in a Pod (default Podman Compose behavior). Docker Compose ignores this flag.

### Verifying Changes

There is no test suite. After editing the script or Compose/Dockerfile, verify with:

```bash
./lint.sh
```

`lint.sh` runs `bash -n` and `shellcheck` on every bash script in the repository (tracked and untracked files minus gitignored ones, detected by shebang, so the target list needs no maintenance when scripts are added or removed), plus `podman compose -f compose.yml config`. It fails with an explicit error if shellcheck is not installed (`sudo apt-get install shellcheck`). When podman is unavailable (e.g. developing inside the container), only the Compose validation is skipped with a warning.

If you edit the `:ro` overlay mounts in `compose.yml` or `prepare_claude_config_ro()` in `claude-container`, run `./test-build.sh --config-ro-only` with the built test image `localhost/claude-test` present (a full `./test-build.sh` run creates it). Separate tests confirm that, with the real `compose.yml` and image, writes to the 11 items are rejected, and that the real launcher creates placeholders, checks types, keeps `--check` write-free, and passes `CLAUDE_CONFIG_DIR` through to compose (an interactive launch through both is done by hand).

If you edit the guard functions in `claude-container` (`guard_*`, `prepare_claude_config_ro()`), run `./test-build.sh --launcher-only`. It launches the real launcher in an isolated environment (temporary `HOME`, empty environment, podman replaced by a dummy) and checks each guard's behavior on a normal launch and under `--check`, plus the environment variables handed to compose. No real podman is needed, so it also runs from a development session inside the container or from CI. The full `./test-build.sh` run includes it.

Changes to `Dockerfile.claude` (the `ENTRYPOINT`'s `setpriv` wrapper) require a `-b` rebuild plus a real launch to verify (see "Security Model" above). A session losing the ability to run `iptables` without `sudo` is the correct, intended state — to inspect the firewall rules themselves, use `podman exec --user root <container> iptables -S` from the host; running `iptables -S` from inside the session will fail once capabilities are stripped.

### Versioning

Releases follow [Semantic Versioning](https://semver.org/) and are managed with annotated git tags (`vX.Y.Z`); each tag gets a GitHub Release created with `gh release create <tag> --notes-from-tag`, reusing the tag message verbatim (no separate CHANGELOG file). Version numbers are judged against the user-visible interface (CLI arguments, the `.claude-container.d/` configuration format, and default behavior):

- **MAJOR** — backward-incompatible changes (changed defaults, removed or incompatible configuration formats — anything that breaks existing usage until the user adapts)
- **MINOR** — backward-compatible feature additions (existing usage keeps working)
- **PATCH** — backward-compatible bug fixes only

Browse the version history on the [GitHub Releases page](https://github.com/jj1xgo/claude-container/releases) (list and subscribe), or with `git tag -n1`.

### References

- [Running Claude Code CLI in a Container (Endpoint Dev Blog)](https://www.endpointdev.com/blog/2026/03/claude-code-cli-in-container/) — Container setup guide by Seth Jensen, the original fork author

### License

GPL-3.0. The original fork ([sethjensen1/claude-container](https://github.com/sethjensen1/claude-container)) is MIT-licensed. See [LICENSE](LICENSE) for details.
