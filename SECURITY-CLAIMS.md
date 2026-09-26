# セキュリティ主張の詳細（試作）

> **この文書は試作段階です**。README.md から移設した C-1・C-2 と、
> Codex 起動対応の C-3・C-4、Claude 経路の project 設定ゲートの C-5 を記載しています。README の全ブロックの移設が決まったものではありません。

---

## C-1

**対象**: capability 剥奪（`compose.yml` の `cap_add` 対策）

**成立条件・脅威モデル**: このガードレール（エグレスファイアウォール）が機能するのは、Claude（および
その子プロセス）がこの許可リスト自体を書き換えられないことが前提になる。`compose.yml` の `cap_add`
（`NET_ADMIN`/`NET_RAW`）は rootless podman では非root ユーザーの ambient set にも入り全子プロセスへ
継承されるため、対策しなければ Claude が sudo を介さず直接 iptables を操作できてしまう（`CAP_NET_RAW`
は `AF_PACKET` 経由で netfilter 自体を迂回することもできる）。

**保証**: `Dockerfile.claude` の `ENTRYPOINT` でコンテナ起動時にこれらの capability を剥奪しており、
iptables の実消費者は `sudo` 経由で root になった `init-firewall.sh` のみに限定される。

**限界・非対象**（2件）:
1. capability の bounding set 自体は削除できない（削除には `CAP_SETPCAP` が必要で、これも与えていない）
   ため、プロジェクトが `.c3c/packages.txt` で file capabilities 付きバイナリ
   （`iputils-ping`・`wireshark` 等）を追加導入すると、そのバイナリ固有の機能に限って capability が
   復活しうる（同梱デフォルトの `packages.txt` にはそのようなバイナリは含まれない）
2. ホスト側から `podman exec` で入るプロセスは `Dockerfile.claude` の `ENTRYPOINT` を経由しないため、
   この制限の対象外である

**根拠**: `Dockerfile.claude` の `ENTRYPOINT`（`setpriv --ambient-caps=-all --inh-caps=-all` ラップ）。

**再確認契機**: 静的（`Dockerfile.claude`・`compose.yml` の変更時に再確認）。

---

## C-2

**対象**: claude-in-chrome 連携（`jj1xgo/claude-container#32`）

**主張**: claude-in-chrome 連携（`mcp__claude-in-chrome__*`）はファイアウォールでは**原理的に遮断できない**。

**理由（保証なし）**: Claude Code 組み込みの claude-in-chrome 連携は `.mcp.json` を介さないネイティブ
機能のため MCP 監査ゲートの対象外であり、コンテナ内から到達・実行可能である。実機調査では、接続時の
新規 TCP 接続はいずれも `claude.ai`/`api.anthropic.com` 系の443番のみで、これは Claude Code 自体の
動作に必須の許可ドメインである——つまりこの経路はエグレスファイアウォールが遮断しようとしている対象
そのものに相乗りしており、許可ドメインを1つも削らずに塞ぐことはできない。

**検知の性質（強制ではなく事後通知）**: ホスト側に表示されるのは Chrome 標準の `chrome.debugger` 通知
（「"claude"がこのブラウザのデバッグを開始しました」）のみで、これは事前承認ではなく**事後通知＋任意
キャンセル**（人間が画面を注視していなければ素通りする fail-open）である。

**限界・非対象**: コンテナ内のコード（プロンプトインジェクションを受けた可能性のあるものを含む）が、
ホストの実ブラウザ（実ログインセッション込み）を人間の事前承認なしに操作しうる——これは「ガードレールは
コンテナ境界」という前提の**外側**にある残存リスクである。

**緩和策（ソフトゲート）**: `.claude/settings.json` の `permissions.deny` に `mcp__claude-in-chrome__*`
を書く方法があるが、他の MCP 向け `permissions.deny` 同様**コンテナ内から書き換え可能なソフトゲート**
にすぎない。

**根拠**: `jj1xgo/claude-container#32`（実機調査の記録）。

**再確認契機**: 静的（claude-in-chrome 連携の実装変更時に再確認）。


---

## C-3

**対象**: `--agent codex` の起動時 MCP 審査（protocol 2、#150）。

**成立条件・脅威モデル**: 信頼する launcher・イメージ・Podman を通常の起動経路で使い、利用者が
表示されたローカル実行定義を確認する。対象はリポジトリ同梱の `/workspace/.codex/config.toml`
（第三者が内容を制御しうる project 設定）で、`CODEX_DIR` の user 設定は運用者自身が書く設定として
対象外にする（Claude 経路の `.mcp.json` ゲートと同じ線引き。README「帰結の重大性で線を引いている」節）。
既存の Claude 用 `.mcp.json` ゲートとは独立している。

**保証する動作**: 対応 protocol の image label を起動前に検査する。検査用コンテナで project 設定を
読み、enabled stdio の名前、command、args、cwd、env、env_vars、environment_id を正規化して hash 化し、
初回・変更時はホストで確認する。project 設定で plugin が有効化されているか marketplace が定義されていれば、確認の前に停止する。
承認記録はホスト側の agent/project 別に保存し、本起動には 1 ファイルだけを `:ro` で渡す。
本起動でも同じファイルを読み直して一致したときだけ Codex へ進む。対象ゼロは空定義として確認なしで記録する。
未知 key・壊れた TOML・型違い・command と url の併記・承認拒否・必要な TTY の欠如・再照合不一致は
停止し、別 CLI へ fallback しない。Codex の版は判定に使わない。

**限界・非対象**:

- `CODEX_DIR` の `config.toml`・plugin キャッシュ・user 層で有効化した plugin は審査しない。
  セッションがそこへ MCP を書き足しても、次回起動の確認では検出しない（Claude 経路の `~/.claude.json` と同じ限界）。
- enabled な定義に `http_headers_helper` がある場合は審査不能として拒否する。helper の無い HTTP と
  disabled server は hash 対象外で、HTTP URL の変更も再承認対象外。通信先は外側の firewall に従う。
- Codex は設定層を table ごとに深く merge する。project の `url` だけのエントリが user 層の同名エントリ
  （helper 付きを含む）の宛先を変えたり、project の `command` だけのエントリに user 層の `args`・`env` が
  合わさったりしうる。確認表示は project 設定の内容だけで、実効の定義とは一致しない場合がある。
- 網羅性（project 層の探索規則、MCP・plugin・marketplace 以外に repo から実行経路を持ち込める設定が無いこと、
  許可 key の集合）は codex-cli 0.156.0 でだけ確認している。`latest` 等で入った別の版が新しい経路を取り込んでも追えない。
- 定義の承認であり、実行ファイル・script・依存パッケージの内容や安全性を保証しない。本起動の
  再照合後の変更、セッション中の設定変更・再接続・plugin の追加、利用者やモデルが直接起動するコマンドは継続監視しない。
- env の値と HTTP header は表示しないが、command/args に秘密を埋め込めば確認表示に出る。
  除去するのは ASCII 制御文字であり、Unicode の bidi 制御等は対象外。内容の秘匿ではない。永続化する承認記録は protocol・hash のみである。
- 固定 repo trust は `.codex/config.toml`、適用対象の hooks・exec policy・sandbox 設定も有効化する。
  MCP 承認はこれらの承認を兼ねず、hooks の信頼確認は Codex の native 機能に委ねる。
  CLI の sandbox/approval 指定は固定するが、追加の書込み先などは native 設定の影響を受ける。
- 審査はイメージ内の python3（3.11 以上）で行う。`tomllib` が無ければ停止する。

**根拠・検証範囲**: `c3c`、`entrypoint.sh`、`codex-mcp-audit.py`、`compose.yml`、
`compose.codex-preflight.yml` と各 Codex 回帰テスト。実装の契約と実機受入は区別し、現在の受入状況は
[README の Codex 節](README.md#codex-cli-を対話で使う) を参照する。

**再確認契機**: 同梱 default の Codex 版を上げるとき。Codex の公開設定形式（`mcp_servers` の key・plugin と marketplace の設定方法）・
project 設定の探索規則・trust、起動経路、承認保存先、マウントの変更時。

---

## C-4

**対象**: Codex 専用 home と既存 Claude 状態の共有。

**保証する動作**: `--agent codex` は専用 `CODEX_DIR` を必須とし、ホストの実 `~/.codex` と同一の
実体を指定した場合は拒否する。コンテナ側は `/home/node/.codex` に固定し、設定・認証・履歴等を rw
で保存する。launcher は認証の本文を解析・表示・ホストから自動コピーしない。新規 ChatGPT 認証は
[第0B-4](docs/superpowers/plans/2026-09-20-c3c-phase0b4-results.md) の専用 fixture で成立した。
`CODEX_HOST_PLUGINS=1` のときだけ、ホストの `~/.codex/plugins/cache` を `CODEX_DIR` の内側（`/home/node/.codex/plugins/cache`）へ `:ro` で重ねる。source は launcher の `$HOME` に固定し、マウント先の symlink・型不一致は起動前に拒否する。

**限界・非対象**: 専用 home は「ホストの実 Codex home を共有しない」という範囲の保護である。
第1段階では共通 Compose の `.claude.json` と `.claude` の rw 共有を残すため、Codex セッションからも
Claude の認証・履歴等を読み書きできる。既存の Claude 設定 12 項目の内側 `:ro` 保護は維持するが、
CLI 間の認証・状態の完全隔離は未達成である。Codex 専用 home 自体もコンテナ内から変更可能なので、
ホストの通常作業でその home を使えば、変更された設定をホストで読み込むことになる。
第0B-4 の認証成功は現在の launcher 全体の受入や、期限切れ認証の refresh 成功を保証しない。
共有したキャッシュの plugin は、`CODEX_DIR/config.toml`（コンテナから変更可能）で有効化されれば読み込まれる。`:ro` が防ぐのはこのマウント経由のホストのキャッシュの改変であり、別の rw マウント（`EXTRA_MOUNT` 等）がキャッシュを含む場合は WARNING を出すだけでその経路は閉じない。また、コンテナ内でどの plugin を有効にするかは制御しない。キャッシュ内の skill・hook の内容の安全性は保証しない。

**根拠**: `c3c` の `CODEX_DIR` guard・`guard_codex_host_plugins()`、`compose.yml`・`compose.codex-plugins.yml` のマウント、`entrypoint.sh` の固定 home。

**再確認契機**: 認証・設定の全面分離、home の指定方法、CLI の認証保存方式、共有マウントの変更時。

## C-5

**対象**: Claude 経路の project 設定ゲート（protocol 1、#163）。

**成立条件・脅威モデル**: 信頼する launcher・イメージ・Podman を通常の起動経路で使い、利用者が表示された設定を
確認する。対象はリポジトリ同梱の `/workspace/.claude/settings.json` と `/workspace/.claude/settings.local.json`
（第三者が内容を制御しうる project 設定。`settings.local.json` は git で追跡していなくても対象にする）。
前提として、Claude Code は workspace trust を `~/.claude.json` の `projects["<repo root>"]` に保存し、
claude-container は全プロジェクトを `/workspace` にマウントして `~/.claude.json` を共有するため、`/workspace` の
trust は全プロジェクトで 1 つになる。一度受け入れると、この 2 ファイルの hook・`env`・`apiKeyHelper` 等の helper・
`statusLine`・allow 規則は確認なしで効く。README「帰結の重大性で線を引いている」節（`claude-container#29`）の
基準（セッション開始と同時の任意コード実行）に当たるため、`.mcp.json` の stdio ゲートと同じ扱いでゲートを置く。

**保証する動作**: `.claude` か `.mcp.json`（symlink を含む）を持つ repo だけを対象にする。イメージの label
`io.c3c.claude-project-audit-protocol` が対応 protocol と一致しなければ `-b` を案内して止める。ホストに python3 が
無ければ止める。検査用コンテナ（非 TTY、stdin は `/dev/null`）でイメージ内の `claude-project-audit.py` が 2 ファイルの
ファイル全体を hash し、表示用の内容と合わせて protocol の JSON 1 文書を出す。launcher はそれを厳密に検証し、
初回・変更時にホストで内容（`env` の値を含む。ASCII 制御文字は除く）を表示して確認する。承認記録
（protocol と hash だけ）はホスト側に atomic に書き、本起動には `:ro` で渡す。本起動の `entrypoint.sh` は
`.mcp.json` ゲートの後・秘密の export より前に同じ helper で再照合し、一致しなければ `/dev/tty` で確認する
（TTY が無ければ止める。記録はしない）。確認を出さずに止める条件: `enabledPlugins` に `false` でない値、
`env` の `CLAUDE_CODE_PLUGIN_*`、空でない `extraKnownMarketplaces`、`.claude/skills/*/.claude-plugin/plugin.json`、
`.mcp.json` のサーバーの `headersHelper`。判定不能として止める条件: 壊れた JSON・最上位がオブジェクトでない・
重複 key、`/workspace` の外を指す symlink・解決できない symlink、通常ファイルでない対象、読み取り・列挙・
パスの確認の失敗、1 MiB を超えるファイル。0 バイトのファイルは中身の無い設定として hash する（c3c 自身が
`~/.claude/settings.json` を 0 バイトで作るため）。環境変数による opt-out は無く、`CLAUDE_PROJECT_APPROVAL_FILE`・
`CC_CLAUDE_START_MODE` は launcher が全経路で明示 export する（`.c3c/env` やシェル環境の値は使わない）。
c3c は対象 repo で git を実行せず、ホストの `~/.claude.json` に書かない。

**限界・非対象**:

- 本起動の再照合の後（Claude Code が設定を読むまでの間を含む）の変更は検出しない。project 設定は稼働中の
  セッションにも反映されうる。書き換える主体には、セッション自身・同じプロジェクトを開いた別コンテナ・ホストの
  エディタがある。検出は次回起動になる。判定・表示・hash は同じ読み取りから作るが、ファイル群を原子的に固定する
  ことは保証しない。
- skills・agents・commands（入れ子を含む）の frontmatter と本文（hook・`allowed-tools`・inline `mcpServers`・
  本文の `` !`cmd` ``）は審査しない。呼び出しにモデルか利用者の判断が入るため #29 の外とし、プロンプト
  インジェクション一般と同じ扱いにする。`CLAUDE.md` とその import、`--add-dir` の追加ディレクトリも対象外。
- コンテナ内で書き換えられた repo の hook が、ホストで Claude Code を起動したときにホストの権限で走る経路は
  ホスト側の trust の問題で、このゲートの外にある。
- `~/.claude.json` の `projects["/workspace"]` に、侵害されたセッションが local scope の MCP 等を書き足す経路は
  残る（README の既存の記述と同じ）。
- 定義の承認であり、hook が呼ぶスクリプトや依存パッケージの内容や安全性を保証しない。
- 表示から除くのは ASCII 制御文字（C0 と DEL）だけで、C1 制御文字（U+0080〜U+009F）や Unicode の bidi 制御等は
  除かない。`env` の値は表示に出る（秘密を置けば見える。永続化するのは hash だけ）。
- `.claude/skills/` の配下に `/workspace` の外を指す symlink や解決できない symlink があると、判定不能で起動しない。
- 網羅性（審査対象の集合）は、実装時（2026-09-26）の公式ドキュメント（permissions の「What runs before you trust
  a folder」、plugins/loading、skills）でだけ確認している。同梱の既定は `CLAUDE_CODE_VERSION=latest` なので、
  新しい版が新しい経路を足しても追えない。`CLAUDE_CODE_PLUGIN_*` を止めるのは、project の `env` から plugin の
  読み込み先が変わるかを確認していないための保守的な措置である。
- `--check` の判定はホスト上での参考実行で、コンテナ内の見え方（symlink 等）と違う場合は起動時の判定が優先する。

**根拠・検証範囲**: `c3c`（`claude_project_gate_needed()`・`guard_claude_project_image_support()`・
`run_claude_project_preflight()`・`check_claude_project_approval()`・`--check` の診断）、`entrypoint.sh`、
`claude-project-audit.py`、`compose.yml`・`compose.codex-preflight.yml` と `tests/test_claude_project_*.py`。
実機受入の記録は PR を参照する。

**再確認契機**: Claude Code の設定形式・workspace trust・plugin の読み込み・MCP の `headersHelper` の仕様の変更、
`CLAUDE_CODE_VERSION` の既定の変更、起動経路・承認保存先・マウントの変更時。
