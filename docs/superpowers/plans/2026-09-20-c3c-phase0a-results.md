# c3c 第0A段階 調査結果

日付: 2026-09-20。対象 commit: `93211ed80ad3e4b4231f40ba5096df6924e76f34`。計画: [2026-09-20-c3c-phase0-validation.md](2026-09-20-c3c-phase0-validation.md)。実行: Opus（Podman ホスト）。

> 本文書は調査結果の記録であり、製品コードを変更していない。0A 完了は G3 完了・製品実装許可ではない。

## 0. 条件（ホスト版・イメージ ID と版・ENTRYPOINT/CMD の inspect・不通過の明記）

**不通過の明記**: 製品 `entrypoint.sh`（firewall・MCP ゲート・秘密配線・cap 剥奪後の実効権限）は本計画では通過していない。全コンテナは製品 ENTRYPOINT（`setpriv` + `tini`）を維持し CMD だけを差し替えて起動した。境界証明には使わない。実験プローブとしてホストで `codex`・`claude` を起動していない（実行・レビュー用ハーネスはホストで動作）。ホスト実設定（`~/.codex`・`~/.claude.json`・`~/.claude`）は参照・共有・コピー・stat のいずれもしていない。

| 項目 | 実測値 | 根拠ログ |
|---|---|---|
| ホスト Git（隔離設定 `hgit`） | `git version 2.53.0` | `host-git-version` |
| ホスト Podman | `podman version 5.8.6`、`rootless=true`、実行者 uid `1000` | `host-versions` |
| 選択イメージ ID | `28b724cd6363`（Id 先頭 12 桁） | `image-selection`、`image.json` |
| 選択理由 | ローカル 4 候補のうち、製品 launcher がこの checkout 用に 2026-09-19 に build したもの（label `project-metadata=1`、`asset-hash` あり、build 入力 `codex-version.txt` = `latest`）。`test-build.sh` 由来のテストイメージは `codex-version.txt` を空にして build するため除外。他 2 候補は別プロジェクト用で build 入力を確認していないため除外。検証用に秘密を焼き込んだイメージではない（製品 build は秘密を焼き込まない） | `image-selection` |
| イメージ base | label `claude-container.base-image=debian:testing`、`/etc/os-release` は `Debian GNU/Linux forky/sid`（計画 Tech Stack の「`debian:stable` ベース」とは異なる。実測値を採る） | `versions` |
| イメージ静的確認 | `IMAGE_STATIC_CHECK_OK`（Entrypoint 一致・User=node・暗黙 Volume なし） | `image.json` |
| イメージ ENTRYPOINT/CMD | `["/usr/bin/setpriv","--ambient-caps=-all","--inh-caps=-all","/usr/bin/tini","--"]` / `["/usr/local/bin/entrypoint.sh"]` | `image-config` |
| コンテナ内 版 | `uid=1000(node)`、`git version 2.53.0`、`codex-cli 0.155.1`、`2.1.278 (Claude Code)`、`python3 -c "import tomllib"` 成功、`versions.rc=0` | `versions` |
| smoke | `smoke.rc=0`。`inspect`: entrypoint がイメージと同一、`cmd=["sh","-c",...]`、`net=none`、binds は `/workspace` と `/probe` の 2 本（`rprivate,nosuid,nodev,rbind`）。`/proc/1/comm` = `tini`。`WS_WRITE_OK`。ホスト側出力ファイルの所有 uid = 1000 = `id -u`。`mcp-started.log`: `cwd=/workspace argc=0`、`notify-fired.log`: `argc=2` | `smoke`、`smoke-markers/`、`stdout-smoke` |

smoke はマーカーの**書込み経路の対照**であり、CLI が定義を読んで起動する対照ではない。

共通条件: 全 `crun` は `--network none --pull never --userns=keep-id:uid=1000,gid=1000`、mount は `$ROOT` 配下の `/workspace`・`/probe`・（Task 3 のみ）`/home/node/.codex` の最大 3 本。コンテナへ渡す env は Git 隔離用（`GIT_CONFIG_NOSYSTEM`・`GIT_CONFIG_GLOBAL=/dev/null`・`GIT_TEMPLATE_DIR`・author/committer）のみ。

## 1. G2: Git 相対リンクの双方向互換

条件: `$ROOT/repo`（`hgit init -b main` + 空 commit）を `/workspace` に mount。両側 Git 2.53.0。

| 判定 | 結果 | 観測 | 根拠ログ |
|---|---|---|---|
| G2-4 版と相対リンク対応 | 成立 | 両側 `git worktree add -h`（rc=129 は usage 表示の終了コード）に `--[no-]relative-paths use relative paths for worktrees` 行あり | `g2-host-help`、`g2-ctr-help` |
| G2-1 ホスト作成→コンテナ利用 | 成立 | ホスト `worktree add --relative-paths .c3c-probe/wt-host -b probe/host` rc=0。生のリンク: worktree 側 `.git` = `gitdir: ../../.git/worktrees/wt-host`、common 側 `gitdir` = `../../../.c3c-probe/wt-host/.git`（**両方相対**）。コンテナ内 `cd /workspace/.c3c-probe/wt-host` から `git rev-parse --git-common-dir` = `/workspace/.git`、`branch --show-current` = `probe/host`、`status --short` 空、commit 成功、`rev-parse HEAD` = `be67fefc1128b8ea6f4bc3cdef5b07fb763fabf5`。ホスト側 `rev-parse HEAD` も同一 hash。コンテナ内 `worktree list` は `/workspace` と `/workspace/.c3c-probe/wt-host` の 2 件 | `g2-host-add`、`g2-host-links`、`g2-host-list`、`g2-h2c`、`g2-h2c-verify` |
| G2-2 コンテナ作成→ホスト利用 | 成立 | コンテナ内 `MODE=relative`、`worktree add --relative-paths .c3c-probe/wt-ctr -b probe/ctr` rc=0。生のリンク: `gitdir: ../../.git/worktrees/wt-ctr` / `../../../.c3c-probe/wt-ctr/.git`（両方相対）。ホスト側 `status --short` 空、`branch --show-current` = `probe/ctr`、commit 成功、hash `4f069965007f364aa05c567ab8938374d5d9cfb5`。コンテナ内 `rev-parse HEAD` も同一 | `g2-c2h`、`g2-c2h-host`、`g2-c2h-verify` |
| G2-3 絶対参照の兄弟 worktree | 成立（列挙可能・利用不可の実例） | ホストで `worktree add $ROOT/wt-sibling -b probe/sibling`（既定=絶対）。生のリンク: `gitdir: $ROOT/repo/.git/worktrees/wt-sibling` / `$ROOT/wt-sibling/.git`（両方ホスト絶対）。コンテナ内 `worktree list --porcelain` にホスト絶対パス `$ROOT/wt-sibling` で列挙され、注記 `prunable gitdir file points to non-existent location`、`ABSENT_IN_CONTAINER` | `g2-sibling-add`、`g2-sibling-links`、`g2-sibling` |

- 実 checkout の既存 worktree: `hgit -C $CC worktree list --porcelain -z` の件数 = **2**（読み取りのみ。パスは記録しない。移動・修復・prune は実行していない）。
- 実行中の逸脱: Step 2 の `.git/info/exclude` 追記は初回失敗（空 template のため `.git/info` が無い）。`mkdir -p` 後に追記した。G2 判定に影響しない。
- 未実測（0B）: 会話内の worktree 移動、`/workspace` mount 先の履歴関連（§7）。Git 版が両側とも 2.53.0 のため、版差がある環境での互換は本結果から言えない。

## 2. G3-A: Codex CLI 表面・設定源・sandbox コマンドの実行経路

条件: codex-cli 0.155.1 / Claude Code 2.1.278（コンテナ内、`--network none`、秘密なし）。help 8 本（`codex --version`・`codex --help`・`codex exec --help`・`codex mcp --help`・`codex mcp add --help`・`codex sandbox --help`・`claude --version`・`claude --help`）は全て rc=0（認証・通信なしで完了）。根拠ログ: `help-*`、`grep-candidates`。

### 2.1 候補オプションの有無（help 行の逐語引用）

| 候補 | 有／無 | help 行（引用元） |
|---|---|---|
| `codex exec --sandbox` | 有 | `-s, --sandbox <SANDBOX_MODE>` … `[possible values: read-only, workspace-write, danger-full-access]`（`codex exec --help`） |
| `codex exec -C/--cd` | 有 | `-C, --cd <DIR>`（`codex exec --help`） |
| `codex exec --skip-git-repo-check` | 有 | `--skip-git-repo-check` / `Allow running Codex outside a Git repository`（`codex exec --help`） |
| `--ask-for-approval` | `codex --help` に有、`codex exec --help` に無 | `-a, --ask-for-approval <APPROVAL_POLICY>`（`codex --help` のみ）。`exec` の実行ヘッダは `approval: never` |
| `--full-auto` | 無（両 help に該当行なし） | — |
| `-c, --config <key=value>` | 有（`codex`・`exec`・`mcp`・`mcp add`・`sandbox`） | `Override a configuration value that would otherwise be loaded from ~/.codex/config.toml … The value portion is parsed as TOML` |
| `-p, --profile` | 有 | `Layer $CODEX_HOME/<name>.config.toml on top of the base user config`（`codex`・`exec`・`sandbox`） |
| `CODEX_HOME` | 有（help 文言に登場） | 上記 `--profile` 行、`--ignore-user-config` 行 |
| `--ignore-user-config` | 有（`exec`） | `Do not load $CODEX_HOME/config.toml; auth still uses CODEX_HOME` |
| `--output-last-message` | 有（`exec`） | `-o, --output-last-message <FILE>` |
| `--permission-profile` | 有（`sandbox`） | `-P, --permission-profile <NAME>` / `Named permissions profile to apply from the active configuration stack` |
| `--sandbox-state-json` | 有（`sandbox`） | `--sandbox-state-json <JSON>` / `JSON value from codex/sandbox-state-meta to apply directly` |
| `notify` | 無（help 行なし。設定キーとしては §3 で実測） | — |
| hooks / trust | 有（`codex`・`exec`） | `--dangerously-bypass-hook-trust` / `Run enabled hooks without requiring persisted hook trust for this invocation. DANGEROUS.`（「persisted hook trust」の存在を示す文言。実効は 0B） |
| `codex --worktree` | 有（`codex`・`exec`） | `--worktree` / `Run the session in a new managed Git worktree`（会話内移動の候補として記録のみ。存否・挙動は 0B） |
| `claude --worktree` | 有 | `-w, --worktree [name]` / `Create a new git worktree for this session (optionally specify a name)`（`claude --help`。会話内移動の候補として記録のみ） |
| `claude` の trust | 文言あり | `The workspace trust dialog`・`directories you trust`（`claude --help`。内容は 0B） |
| `codex mcp` 副コマンド | `list`・`get`・`add`・`remove`・`login`・`logout` | `codex mcp --help` |
| `codex mcp add` の書式 | `codex mcp add [OPTIONS] <NAME> (--url <URL> \| -- <COMMAND>...)` | `codex mcp add --help`。`--env <KEY=VALUE>`（stdio のみ）、`--bearer-token-env-var`（HTTP のみ）。`cwd` のオプションは help に無い |

README の `codex exec --sandbox read-only -C /workspace --skip-git-repo-check` に使う 3 つは `codex exec --help` に全てある。

### 2.2 設定源（対象版で確認した範囲。「網羅した」とは書かない）

| 設定源 | 対象版での確認手段 | 保存先 | コンテナから書けるか |
|---|---|---|---|
| (1) user: `$CODEX_HOME/config.toml` | §3 で `codex mcp add` が書く事実を実測 | `/home/node/.codex/config.toml`（rw mount 内） | 書ける（実測） |
| (2) system 層（`/etc/codex` 等） | `cfg-paths`: `ls: cannot access '/etc/codex': No such file or directory`。検査した `/etc/codex` は不在。他の system 層の有無は未確認。`/home/node/.codex` も mount しない限り不在。`env | grep -i codex` は空、`HOME=/home/node` | 検査パスは不在。他の層は未確認 | mode/実効権限は未実測 |
| (3) 起動引数 `-c`・`--profile` | help（§2.1） | なし（起動ごと） | 起動側が制御 |
| (4) project 側の信頼設定（`projects` テーブル・trusted project 層） | 対話確認が要る | 未実測 | **0B** |
| (5) plugin・cloud defaults・managed config | help に `--include-managed-config`（`sandbox`）、`--enable/--disable <FEATURE>` あり。公式資料（2026-09-20 事前観測の優先順位 CLI > trusted project > profile > user > cloud defaults > system > builtin）を引用。対象版での実効は**未確認** | 未実測 | 未実測 |

### 2.3 G3-A4: モデル不要の sandbox コマンドの実行経路

| 観測 | rc | 内容 | 根拠ログ |
|---|---|---|---|
| `sb-pc`（素の対照、同じ workspace mount・uid） | 0 | `PC_WRITTEN`、`ws-sb/pc.txt` 作成（uid 1000） | `sb-pc`、`stdout-sandbox` |
| `sb-ro`（`codex sandbox -c 'sandbox_mode="read-only"' -C /workspace sh -c ...`） | 2 | `error: the following required arguments were not provided: --permission-profile <NAME>` / `Usage: codex sandbox --permission-profile <NAME> --config <key=value> --cd <DIR> <COMMAND>...`。`INNER_BEGIN` 未出力（内部未到達）。`sb-ro.txt` 不在 | `sb-ro`、`stdout-sandbox` |
| `sb-ww`（同 `workspace-write`） | 2 | 同一エラー。`INNER_BEGIN` 未出力。`sb-ww.txt` 不在 | `sb-ww`、`stdout-sandbox` |

**判定 G3-A4: not run**。理由: 対象版の `codex sandbox` は `--permission-profile <NAME>` を必須引数とし、有効な NAME は `--help` にも、`codex exec` が `codex-home/` に展開した同梱資料にも記載がない（検索出力は権限一般に関する英文 1 行のみで、NAME や設定書式の記載は得られなかった。根拠: `stdout-profile-search`）。help は `-P` を必須表記なしで列挙する一方、今回の実行は必須引数エラーになった。必須になる条件は未確認。計画の「help に無い引数を推定で使わない」に従い、NAME を推定して再実行しなかった。内部コマンドに到達していないため、`sb-ro.txt`・`sb-ww.txt` の不在を**保護成功と解釈しない**。`sandbox_mode` 候補の強制力は本計画では確定できない。補足観測: `codex sandbox` は `codex-home-sandbox/tmp/arg0/codex-arg0*/.lock` を作成した（設定ホームへの書込みは引数エラーでも起きる。根拠: `stdout-sandbox`）。`exec-noauth` のログには `warning: Codex could not find bubblewrap on PATH … Codex will use the bundled bubblewrap in the meantime.` があり、対象版は同梱 bubblewrap を使う（製品コンテナの cap 剥奪下で動くかは 0B）。

## 3. G3-B: 設定登録・TOML 構造・解析不能時の挙動・MCP/notify マーカー観測

条件: `$ROOT/codex-home`（空・mode 700）を `/home/node/.codex` に rw mount。`/probe/bin/mcp-marker.sh`・`/probe/bin/notify-marker.sh` は smoke で書込み経路を確認済みの無害な代役。

### 3.1 G3-A1: `codex mcp add` の保存先と TOML 構造 — 成立

- `mcp-add` rc=0、出力 `Added global MCP server 'probe'.`
- `mcp add` と `mcp list` の後、`codex-home/` の増分ファイルは `config.toml` の 1 本のみ（`find -type f`、`stdout-mcp-add-list`）。
- `config.toml` の全文（逐語）:
  ```toml
  [mcp_servers.probe]
  command = "/probe/bin/mcp-marker.sh"
  ```
- `toml-check` rc=0: `tomllib` で `{"mcp_servers": {"probe": {"command": "/probe/bin/mcp-marker.sh"}}}`、`mcp_servers.probe.command` 一致。
- `mcp-list` rc=0: `Name probe / Command /probe/bin/mcp-marker.sh / Args - / Env - / Cwd - / Status enabled / Auth Unsupported`。
- 根拠ログ: `mcp-add`、`mcp-list`、`toml-check`。

### 3.2 notify をルートに置いた構造 — 成立

- `notify = ["/probe/bin/notify-marker.sh"]` をファイル先頭に置く（末尾追記だと `[mcp_servers.probe]` テーブル内キーになる）。
- `toml-check2` rc=0: `root-notify-ok`。`mcp-list2` rc=0、Step 3 と同一の一覧（notify 追加で読めなくならない）。
- 根拠ログ: `toml-check2`、`mcp-list2`。

### 3.3 G3-A2: 解析不能な設定での挙動（`codex mcp list`）— 成立（この操作では解析不能で停止）

- `codex-home-broken/config.toml` = 上記 + `\n[mcp_servers.broken\ncommand = 1\n`。
- `mcp-list-broken` rc=1。出力（逐語）:
  ```
  Error: failed to load bootstrap configuration

  Caused by:
      0: /home/node/.codex/config.toml:5:20: unclosed table, expected `]`
      1: TOML parse error at line 5, column 20
  ```
- 一覧は出力されない。`codex exec` 経路での挙動は 0B で別途確認する。
- 根拠ログ: `mcp-list-broken`。

### 3.4 G3-A3: 認証なし `codex exec` での MCP・notify マーカー — 成立（マーカー行あり）

- `pre-exec-markers/states`: `mcp-started.log present` / `notify-fired.log present`（いずれも smoke の 1 行のみ。`wc -l` = 各 1 行。add/list/broken の各操作ではマーカーが増えていない）。
- Step 6 開始前に両ログを空にした後、`exec-noauth`: `timeout 120 codex exec --sandbox read-only -C /workspace --skip-git-repo-check "Reply with exactly the single word: pong"`。
- rc=124（内側 `timeout 120` による強制終了）。`pong` は返らない。出力ヘッダ（逐語）: `workdir: /workspace` / `model: gpt-6-astra` / `provider: openai` / `approval: never` / `sandbox: read-only` / `Reading additional input from stdin...`。以後 `ERROR codex_api::endpoint::responses_websocket: failed to connect to websocket: IO error: failed to lookup address information: Try again, url: wss://api.openai.com/v1/responses` が繰り返され、`Reconnecting... 5/5` → `Falling back from WebSockets to HTTPS transport` → `Reconnecting... waiting for network` で timeout。認証エラーの文言は出力されていない（認証処理との前後関係は未確認）。
- `exec-noauth-markers/states`: `mcp-started.log present` / `notify-fired.log empty`。
- `mcp-started.log`（逐語）: `2026-09-20T11:42:36+09:00 pid=89 ppid=10 cwd=/workspace argc=0`。
- **判定 G3-A3: 認証情報なし・通信不能でも stdio MCP サーバーが起動した（`cwd=/workspace`）**。マーカーは 11:42:36、最初に記録された接続エラーは 11:42:42（同一タイムゾーン換算）である。接続試行そのものや認証処理との前後関係は、このログから確定できない。ユーザー入力はログにあるが、モデル応答は得られていない。notify はこの経路（応答なし・timeout 終了）では発火しなかった。実認証での起動時期の対照と、承認済み定義との対照は 0B 必須。**未起動を保護成功とは書かない**（本項は起動ありのため該当しない）。
- `codex-home/` の増分ファイル（`exec-noauth-files.log`、`env.sh` より新しいもの。`skills/.system/` 配下 6 skill 分は省略）: `.sandbox_migration`（内容 `v1`）、`.tmp/plugins.sync.lock`、`config.toml`、`goals_1.sqlite{,-shm,-wal}`、`logs_2.sqlite{,-shm,-wal}`、`memories_1.sqlite{,-shm,-wal}`、`queue_1.sqlite{,-shm,-wal}`、`state_5.sqlite{,-shm,-wal}`、`thread_history_1.sqlite{,-shm,-wal}`、`installation_id`、`sessions/2026/09/20/rollout-<時刻>-<session id>.jsonl`、`shell_snapshots/<session id>.<n>.sh`、`skills/.system/.codex-system-skills.marker` と `skills/.system/{imagegen,openai-docs,plugin-creator,review-agent,skill-creator,skill-installer}/`、`thread-writer-locks/.coordination.lock`・`<session id>.lock`、`tmp/arg0/codex-arg0*/.lock`。
- 根拠ログ: `exec-noauth`、`pre-exec-markers/`、`exec-noauth-markers/`、`exec-noauth-files`。

### 3.5 0B 必須（§2・§3 から）

信頼記録の保存先・偽造可否、hook trust の対話／再開／非対話、モデル経由の sandbox 実効、`codex exec` 経路での解析不能設定の挙動、実認証での MCP 起動時期の対照は **0B 必須**。

## 4. 判定表と 0B 必須の未実測表

### 表 A: 0A の判定

| 判定 | 結果 | 根拠ログ名 |
|---|---|---|
| G2-1 ホスト作成（相対）→コンテナ利用・commit・hash 一致 | 成立 | `g2-host-add`、`g2-host-links`、`g2-h2c`、`g2-h2c-verify` |
| G2-2 コンテナ作成（相対）→ホスト利用・commit・hash 一致 | 成立 | `g2-c2h`、`g2-c2h-host`、`g2-c2h-verify` |
| G2-3 絶対参照の兄弟 worktree の列挙と利用不可診断 | 成立（列挙可・`prunable` 注記・`ABSENT_IN_CONTAINER`） | `g2-sibling-add`、`g2-sibling-links`、`g2-sibling` |
| G2-4 両側 Git 版と `--relative-paths` 対応 | 成立（両側 2.53.0） | `host-git-version`、`versions`、`g2-host-help`、`g2-ctr-help` |
| G3-A1 `codex mcp add` の保存先と TOML 構造 | 成立（`$CODEX_HOME/config.toml` の `[mcp_servers.<name>]` / `command`） | `mcp-add`、`mcp-list`、`toml-check` |
| G3-A2 解析不能な設定での挙動（`mcp list`） | 成立（rc=1、`failed to load bootstrap configuration` で停止） | `mcp-list-broken` |
| G3-A3 認証情報なしの MCP/notify 起動有無 | 成立（認証情報なし・通信不能でも MCP 起動。認証処理・接続試行との前後は未確認。notify は未発火） | `exec-noauth`、`pre-exec-markers/`、`exec-noauth-markers/` |
| G3-A4 モデル不要 sandbox コマンドの経路と実効 | **not run**（`codex sandbox` が `--permission-profile <NAME>` を必須とし、有効 NAME が help・同梱資料に無い。推定使用は禁止事項。内部未到達） | `sb-pc`、`sb-ro`、`sb-ww`、`stdout-sandbox` |

### 表 B: 0B 必須・本計画では未実測（0A 完了で消さない）

| 項目 | 仕様根拠 | 0B での前提 | 状態 |
|---|---|---|---|
| 実認証での MCP 起動時期（起動直後／最初のターン）と承認済み定義の起動対照 | G3 | 使い捨て `CODEX_DIR`・限定認証・製品 firewall 経由 | not run |
| 信頼記録（`projects` 等）の保存先とコンテナからの偽造可否 | G3 | 対話起動（TTY） | not run |
| モデル経由の `--sandbox read-only` 実効（ツール呼出しイベント + OS 拒否） | G3 | 実認証 | not run |
| hook/notify の発火（対話・再開・非対話）と hook trust | G3 | 実認証 | not run |
| 変更済み・未承認・解析不能な定義の実行前停止（会話内再読込） | G3・§7 | 実認証 | not run |
| 両 CLI の同一会話内 worktree 移動（A→B、B 変更後の再移動、判定失敗） | §7 | 使い捨て repo・無害定義・実認証 | not run |
| 製品 entrypoint 経由の firewall・cap 剥奪・`:ro` 保護・ホスト `~/.codex` 不変 | §9 | 実コンテナ | not run |
| `codex sandbox` の `--permission-profile` の有効値と `sandbox_mode` 候補の強制力（0A で not run になった G3-A4 の残り） | G3 | 対象版の資料確認、または `-c permissions.<name>` 等の設定書式の確定 | not run |
| 同梱 bubblewrap（`Codex will use the bundled bubblewrap`）が製品の cap 剥奪・`--network none` 相当の下で動作するか | G3 | 実コンテナ | not run |

### 止める条件の該当

- 同じプローブを 2 回実行して観測が食い違う: 該当なし（各プローブは 1 回。`mcp list` は `mcp-list`・`mcp-list2` で同一出力）。
- `$ROOT`・台帳外に残留物: 該当なし（§5）。
- 禁止命令を使わないと進められない Step: G3-A4（`--permission-profile` の NAME 推定）。not run とし、持ち主判断待ち。

### G1/G4 への事実の引き継ぎ（引用のみ）

- 両側の `git rev-parse --git-common-dir`: コンテナ内の worktree（`/workspace/.c3c-probe/wt-host`）から `/workspace/.git`。ホスト側は `hgit` の commit・`rev-parse HEAD` が同一 hash を返したことから同じ common dir を解決している（明示的な `--git-common-dir` 出力はホスト側では採取していない）。（G1 へ）
- 絶対参照 worktree の列挙結果: コンテナ内 `worktree list --porcelain` に `worktree $ROOT/wt-sibling` / `prunable gitdir file points to non-existent location` が含まれる。（G1・G2 へ）
- 実 checkout の既存 worktree 件数: 2（読み取りのみ）。（G1 へ）
- `codex mcp add` の保存先: `$CODEX_HOME/config.toml`（`Added global MCP server`）。`mcp add` と `mcp list` の後の一覧は `config.toml` の 1 本（`stdout-mcp-add-list`）。`codex exec` 1 回で `codex-home/` に sqlite 6 系統・`sessions/`・`shell_snapshots/`・`skills/.system/`・`installation_id`・`.sandbox_migration`・各種 lock が生成される（§3.4 の一覧）。（G4 へ）
- `codex exec` は `--network none`・認証なしでも `wss://api.openai.com/v1/responses` への接続を試み続け、認証エラーで停止しない（§3.4）。（G3 へ）

**0A 完了は G3 完了・製品実装許可ではない。第1・第3段階の詳細計画は 0B の結果を待つ。**

## 5. 残留物・後始末・レビュー経過

### 証拠の保存範囲

`logs/` の各観測ログに加え、実行時に画面へだけ出していた Bash tool result 29 件を、ROOT 削除後に実行ハーネス記録から `execution-bash.jsonl` へ保存した。再実測ではない。主要出力を改変せず `logs/stdout-*.log` に抜き出し、各主張の根拠に補った。

| 確認対象 | 保存した実行時出力 |
|---|---|
| smoke 出力ファイルの所有 uid | `stdout-smoke` の `ls -ln` |
| MCP 登録・一覧後に config.toml 1 本 | `stdout-mcp-add-list` の `find -type f` |
| pc.txt の存在、sb-ro.txt/sb-ww.txt の不在、sandbox home の lock | `stdout-sandbox` の一覧 |
| 同梱資料の profile 検索（無関係な英文 1 行のみ） | `stdout-profile-search` |
| cleanup rc・対象コンテナ 0 件・image 保持・status・worktree 件数 | `stdout-cleanup` |
| ROOT 削除 rc・削除後の不在・対象コンテナ 0 件 | `stdout-remove-root` |
| 実行後 lint の終了コードと出力 | `stdout-lint`、退避先直下 `lint.log` |

### 後始末（自分の資源に限る）

- `RUN_ID`: `c3c-0a-797779-afmvnm`。台帳のコンテナ 26 件（全て `crun` が各観測後に `podman rm -f` 済み）。
- `cleanup` rc=0、`rm-failed` なし。`podman ps -a --filter label=c3c.phase0.owner=$RUN_ID` = 0 件。
- 選択イメージ `28b724cd6363` は削除していない（`image-kept`）。`podman build`・`rmi`・`prune` は実行していない。
- 退避先: `$CC/.claude/test-results/<RUN_ID>/`（`logs/`・`ledger.tsv`・`env.sh`・`bin/`・`out/`。外側 `.gitignore` と ops 側 `.gitignore` の両方で除外済み。実測の退避ログはここ。実行ハーネスの記録もローカルに保持）。退避成功後に `cleanup --rm-root` で `$ROOT` を削除した（rc=0、`/tmp/c3c-0a.*` 不在）。
- `hgit -C $CC status --short` の増分は本ファイル（`docs/superpowers/plans/2026-09-20-c3c-phase0a-results.md`）のみ。実 checkout の worktree 件数は開始時と同じ 2。製品ファイル・元計画・仕様は変更していない。commit・push・PR 作成はしていない。
- ホスト実設定（`~/.codex`・`~/.claude.json`・`~/.claude`）は内容・stat とも参照していない。実験プローブとしてホストで `codex`・`claude` を起動していない（実行・レビュー用ハーネスはホストで動作）。

### 実行時の逸脱（計画からの差分）

| 逸脱 | 理由 | 影響 |
|---|---|---|
| Task 1 Step 3 の `read -p` を変数代入で代替 | 非対話実行。選択理由と ID は `image-selection` ログと §0 に記録 | なし |
| Task 2 Step 2 の `.git/info/exclude` 追記が初回失敗 → `mkdir -p .git/info` 後に追記 | 空 `GIT_TEMPLATE_DIR` のため `.git/info` が生成されない | `$ROOT/repo` 内のみ。G2 判定に影響なし |
| Task 3 Step 7 の `sb-ro`・`sb-ww` を再試行しない（G3-A4 not run） | `--permission-profile <NAME>` の有効値が help・同梱資料に無く、推定使用は計画の禁止事項 | G3-A4 は 0B（表 B）へ |
| 計画 Tech Stack の「`debian:stable` ベース」 | 選択イメージの実測は `debian:testing`（forky/sid） | 版差として §0 に記録。結論の転用なし |
| `./lint.sh` の実行 | AGENTS.md の要件（ファイル編集後）。計画には明記なし | 下記 |

### lint

`./lint.sh` 終了コード 0、`lint OK`（shellcheck 0.11.0、対象 14 本、警告 0）。本ファイル追加は shell スクリプトを含まないため lint 対象の変更はない。

### レビュー経過

- 第1巡 Codex 標準レビュー: Critical 0・Important 0・Minor 0。根拠ログと結果を照合。
- 第1巡 Fable: Critical 0・Important 2・Minor 4。MCP 起動の時系列の断定と、画面出力だけだった根拠の保存を指摘。
- 修正: 時系列を観測範囲へ限定し、実行時 Bash 出力を保存して根拠を追加。対照の mount 表現、help と実行時エラーの差、推測表現、進捗見出しも修正。セルフレビューで system 層の断定を検査パスの範囲に限定し、資料検索の出力説明も訂正。
- 実行担当 Opus は修正開始時に利用上限へ到達したため、親 Codex が文書修正を引き継いだ。追加プローブは実施していない。
- 第2巡 Codex 標準レビュー（確認限定）: **Critical 0・Important 0・Minor 0**。前巡6件の修正、保存した stdout 7 本と元 tool result の一致、直接回帰なしを確認。
- 第2巡 Fable: **not run（利用上限）**。呼出しは利用上限エラーで終了し、レビュー応答は得られなかった。その後、持ち主が「暫くは Codex だけで進めて」と指定したため、当面の確認ゲートは Codex の第2巡で代替する。Fable の未実施という履歴は保持し、自動で再呼出ししない。
- 文書修正後も `./lint.sh` 終了コード 0、`lint OK`。レビュー原文は退避先の `reviews/` に保持。
- 実測・後始末・指摘修正は完了。Codex の確認限定レビューでは未対応 Critical/Important は 0 件。Fable 再確認は持ち主指定により当面ゲートにしない。表 B の未実測は引き続き残る。
