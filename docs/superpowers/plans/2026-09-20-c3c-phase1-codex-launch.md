# c3c 第1段階: Codexの標準CLI起動と起動時MCP審査

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**状態:** 計画レビュー確定。Tasks 1–3 の実装と回帰検証は完了（未コミット）。Task 4 の実機受入と Task 5 の文書・最終レビューを進行中。実装に対する過去の Fable レビューは利用上限で未完了。現在の受入状況と PR 前レビューの手順は[結果記録](2026-09-20-c3c-phase1-results.md)を参照。

**Goal:** 既存Claude起動を維持し、明示的にCodexを選んで同じ外側境界の中で標準CLIを使えるようにする。c3cの起動時MCP承認をCLIのnative trustと分ける。

**Architecture:** launcherの選択肢、通常初期化後のCLI分岐、小さなMCP一覧正規化helperを追加する。nativeの設定解決を再実装しない。起動前の検査用コンテナと本起動の両方で同じhelperを使い、host側の独立承認hashと照合する。判定不能な実行定義は診断して拒否する。

**Tech Stack:** Linux/rootless Podman、bash、Python3 stdlib、codex-cli0.155.1、既存Composeとテスト群。

**Spec:** [段階移行仕様](../specs/2026-09-20-c3c-incremental-design.md) G3・第1段階。[第0B-9結果](2026-09-20-c3c-phase0b9-results.md)。初期基点main `93211ed`。

## 提供する操作と範囲

- `claude-container --agent codex <directory>` を追加。無指定と `--agent claude` は現行Claude。未知値・値欠落・複数指定はexit2、別CLIへのfallbackなし。
- `--read-only` は `--agent codex` と併用した諮問用。通常はworkspace-write。CLIの標準UI・モデル選択・MCP登録・履歴/再開操作を利用する。最終的な `c3c` 名・`.c3c/`・前回選択の記憶は第2段階、worktree作成/移動は第3段階。
- `--agent` とclean系は意味が曖昧なので併用拒否。`--check --agent codex` は既存の無起動・無書込みを保ち、Codex導入/専用home等の静的前提を診断する。実効MCPの動的照合はnot runとして明示し、承認済みとは報告しない。
- 任意のCLI引数転送はこの段階では追加しない。native CLI内の操作は維持する。launcherが指定する設定解決用の固定overrideは、検査と本起動の両方で一致させる。一覧取得用subcommandと対話起動用引数そのものの一致は要求しない。
- Codexは既存opt-inビルドを維持。最初の対応版は0.155.1。未知版を同じschemaとして黙認せず、対応確認が必要と診断する。
- `CODEX_DIR` 専用homeを必須とし、ホスト実体の `~/.codex` を拒否する既存guardを維持。認証はユーザーの選択に従い専用homeでの新規ChatGPTログインを使える。auth本文の表示・独自解析・hostからの自動コピーは追加しない。

## G3の具体的な契約

### 起動時だけの独立承認

審査対象はc3cが起動するCodexの設定済みMCPにあるローカルcommand経路。user/project/active pluginの解決をnative `codex mcp list --json`へ委ねる。これは登録用の設定形式を変えない。c3cが起動した後の設定変更/再接続は標準機能であり継続監視しない。この限界をREADMEとSECURITY-CLAIMSへ記載する。

既存Claudeの `.mcp.json` ゲートは変更しない。Codex時にはClaude用ゲートをCodexの審査に代用せず、同じ共通初期化内の選択した側のゲートを通す。

### native一覧の取り扱い

- 一覧helperはnative CLIを子プロセスとして期限60秒・独立process groupで実行し、終了時に群の停止を確認する。stdoutはメモリ上のJSONとして扱い、env値・HTTP headersを含む生出力はログ/承認記録へ保存しない。stderrの無加工転送も避け、失敗時は段階・経過秒・終了コード（期限超過はtimeout）を示す。native内部の通信段階を推測で表示しない。
- native JSONから対象版の型を厳密に検証する。top-level array、name、enabled、transportの型が不明なら拒否する。stdioはcommand/args/env/env_vars/cwdをすべて保持し、配列順を保ったcanonical JSONからhashを得る。server名で整列し、object keyをsortする。auth_statusは変動する診断値なのでhashに入れない。
- enabled=falseは起動対象から除外する。enabled stdioを審査する。HTTPは `http_headers_helper=null` の場合に限りローカルcommand無しとして扱い、外側の通信制限を維持する。helperがnon-null（本文か `<redacted>` かを問わず）なら「対象版の一覧では実行定義を完全に審査できない」と拒否する。設定自体を自動削除/無効化せず、利用者へ理由を示す。
- 未知transport、未知のローカル実行経路、対象版と異なる応答は空として通さない。active pluginのMCPが一覧へ入ることは、固定local fixtureを実物CLIで検証する。runtime contributionやCLI内で後から起動する組込み機能を「設定済みMCP一覧が完全に監視する」と主張しない。
- `mcpServerStatus/list` は接続を開始しうるため起動前審査に使わない。`config/read`だけでもplugin由来MCPが揃った扱いにしない。
- 一覧は認証情報をnative CLI内部で参照し、helper無しHTTPではOAuth discovery通信を行う場合がある。通常firewall適用後、Codex用の固定home/CLI実体を確定し、既存の秘密exportを完了した同一環境で実行する。Codexの検査・再照合・本CLIが参照する環境を揃える。Claudeのゲートと秘密exportの順序は変更しない。c3cがauth本文を取り出す機構は作らない。

### 検査と本起動の一致

作業基点は `/workspace`。c3cは利用者が明示して起動したprojectをtrustedとして扱い、nativeの全体TOML override `projects={"/workspace"={trust_level="trusted"}}` を検査と本起動の両方に渡す。これにより検査でproject設定を無視し、本起動のtrust操作後だけMCPが現れる差を防ぐ。第3段階のworktree追加trustは別計画で扱う。native既定trustを無言で当てにしない。

1. Codex経路はimage不在なら、`-b`なしでもstage→明示buildを行う。imageが存在し`-b`なしならbuildしない。`-b`ありなら明示buildを行う。いずれもコンテナrunの前に固定image label `io.c3c.codex-audit-protocol=1` をinspectする。label欠落/未知値ではpreflight自体を起動しない。`-b`によるビルド後は実際に起動するimageを再inspectする。通常起動と `--check` で共有guardを使い、既存の一般asset driftの警告とは別に強制する。対応imageでだけ、同じmount・working directory・固定Codex引数の検査用コンテナを起動する。firewall/capability剥奪後に、固定 `CODEX_HOME=/home/node/.codex` をexportし、CLI実体をイメージ内の導入済み絶対パスとして確定する。この2つとHOME/PATHは秘密exportで差替えさせない。既存の秘密exportを完了してからsnapshotし、agentを起動せず終了する。本起動も同じ順序でverifyしてからexecする。
2. 検査用出力はprotocol version・Codex version・canonical hash・サニタイズした表示用command/args/cwd/env_vars/envのキー名・対象件数だけ。command/argsには利用者が埋め込んだ秘密が含まれ得るため、protocol自体は永続ログへ保存せず、必要な一時fileは0700/0600で管理して終了時に削除する。保存する正本はhashと非秘密metadataのみ。env値・HTTP headersは表示しない。確認対象ゼロも明示的な有効結果とする。ログとprotocolを混ぜず、破損/欠落/重複応答は拒否する。
3. host launcherで保存先をproject env読込前にfreezeする。既存Claude台帳とは別に、現在のproject識別子とagent/versionを含むキーへhashを保存する。dir0700/file0600、同一dir一時ファイルからatomic replace。表示の制御文字除去は既存方針を継承し、拒否・TTY無し・EOFはCodexを起動しない。
4. 承認記録は専用固定containerパスへ`:ro`。本起動のentrypointでも秘密export後に同じ固定home/CLI実体のhelperから再計算し、一致時だけCodexへ進む。検査と実行の間に設定が変われば拒否する。コンテナ内へ台帳ディレクトリ全体やhost socketを公開しない。
5. helperとentrypointはimageの固定アセット。ビルドステージング・asset hash・再ビルド診断へ加える。実行モード/agent/承認パスをproject envで上書きできないようにする。

この二重照合も、最後の照合後の書換えや参照先プログラムの内容不変を保証しない。これは現行TOFUの限界と同じであり、継続監視へ拡大しない。

## Global Constraints

- 現行のcapability剥奪、firewall適用順、secretsの非export区分、`:ro`保護、env非source、asset hashを維持。編集前に `docs/development-invariants.md` の対象節を読む。
- `.claude.json` 共有の全面解消とrepo共通設定は後続段階。Codex導入で新たなホスト実行経路を増やさない。
- branch/worktree/差分を再確認し、製品編集は専用worktreeで行う。他セッションのtrial worktreeに触れない。commit/push/PRは既存の承認範囲を超えて自動実行しない。
- private認証homeや試験ログの絶対パスを公開文書へ書かない。実認証テストの生会話・native設定全文を公開しない。

## Files / Interfaces

変更候補: `claude-container`、`entrypoint.sh`、`compose.yml`、`Dockerfile.claude`、`test-build.sh`、`README.md`、`SECURITY-CLAIMS.md`、`docs/development-invariants.md`、必要なら `lint.sh`。新規候補: `compose.codex-preflight.yml`、`codex-mcp-audit.py`、`tests/test_codex_mcp_audit.py`、`tests/test_codex_launch.py`。命名は本計画に固定する。

helperのinterfaceは `snapshot`（native一覧取得→strict normalize→version/hash/表示用情報）、`verify <approved-file>`（snapshotとreadonly記録の一致、成功0/不一致非0）。内部入力は `CC_AGENT=claude|codex`（未設定のみclaude既定、空文字を含む不正値は拒否）、`CC_CODEX_START_MODE=run|preflight`、`CC_CODEX_READ_ONLY=0|1` に固定する。host launcherはCLI解析から導出した値をproject env読込前にfreezeし、Compose起動にはその値だけを明示して渡す。利用側envの許可リストへ追加しない。container側もenumを検証する。preflightでは初期化ログが出る前に元stdoutをfd3へ保持し、通常stdoutをstderrへ向け、snapshotの1 JSON文書だけをfd3へ出す。hostはstdout全体が1つのprotocol JSONであることを検証し、余分な文字列があれば拒否する。count=0も独立した空定義hashとして本起動へreadonlyで渡すが、人間へのMCP実行確認は省略できる。

### レビューで確定した補足契約

- **検査用の非TTY経路:** 固定 `compose.codex-preflight.yml` で同じserviceの `tty: false` / `stdin_open: false` のみを上書きする。preflightの `podman compose run` にも `-T` を渡し、host側stdinは `/dev/null`。通常起動のTTYは維持する。overrideをstaging/asset hash/Compose検証の対象へ加える。実物でstdoutとstderrの分離、stdoutがprotocol 1文書だけであることを受入条件にする。`podman-compose run --help`で `-T` の存在は確認済みだが、実コンテナでの分離は実装後の検証である。
- **trustの範囲:** 固定trust overrideはrepo側 `.codex/config.toml` と適用対象のhooks・exec policy・sandbox設定等も有効化する。MCP以外の定義をc3cが承認した意味にはせず、hooksはnativeの個別確認へ委ねる。固定CLI引数で指定するsandbox/approvalは維持し、追加のworkspace-write書込み先等はnative設定の影響を受けることをREADME/SECURITY-CLAIMSへ記載する。壊れたproject設定は起動失敗となり、設定を無視して進めない。
- **Claude設定共有の残余:** 第1段階では共通Composeの `.claude.json` / `.claude` のrw共有と内側の既存ro保護を維持する。CodexセッションにもClaude認証・履歴等のrw状態が見えるため、CLIごとの認証隔離を達成したとは扱わない。Codex専用homeという説明はCodexのhost homeを共有しない意味であり、Claude状態まで隔離する意味ではない。README/SECURITY-CLAIMSへ明記し、全面分離はG4で扱う。受入試験は専用のClaude fixtureを用い、持ち主の実Claude設定/認証を検証に露出させない。
- **承認保存先と清掃:** `MCP_APPROVAL_STORE/codex/$PROJECT_NAME/0.155.1.json` に固定する。agentは固定subdirectory、版は対応版だけを採用し、projectは現行launcher算出値を使う。保存先はproject env読込前にfreezeする。既存Claude記録は変更しない。`--clean <dir>` はそのprojectのClaude記録とCodex subdirectory全体（過去版を含む）を削除し、他projectは残す。`--clean-all` は既存store全体の削除で双方を消す。`--check --agent codex` は記録の存在・形式だけを静的診断し、実効定義の一致/承認済みとは表示しない。
- **hash対象:** 正規化文書を `{protocol_version: 1, codex_version: "0.155.1", servers: [...]}` とし、serversはenabled stdioのみ、各要素はnameとtransportのtype/command/args/env/env_vars/cwdを含める。enabled=falseの全serverと、helper無しenabled HTTPは一覧schemaを検証した後にhashから除く。HTTPのURL変更は外側の通信制限の対象で、ローカルcommandの再承認対象ではない。helper有りHTTPはhash計算前に拒否する。auth_status/disabled_reason/timeout/HTTP header値はhashに含めない。name重複・JSONの重複key・未知のtransportフィールドは判定不能として拒否する。
- **版の取得:** 同じ固定絶対パスの `codex --version` を期限5秒で実行し、単一行 `codex-cli 0.155.1`（末尾改行だけ除去）と厳密比較する。非0・空・未知形式/版は拒否する。listの60秒期限とは別に管理する。60秒で全環境を保証するとはせず、期限超過時は停止する。認証あり受入でcold/warm両方の経過時間を記録する。
- **preflightの副作用:** native CLIによるcloud config cache更新、auth refresh、OAuth discovery等の通信・専用homeへの書込みがあり得る。agent/MCP commandを起動しないことと、副作用ゼロは区別する。通常起動までにfirewall/DNS初期化が2回走ることと所要時間もREADMEへ記載する。
- **既存テストとlabel:** fd3保存は抽出境界より前のpreflight分岐だけに置き、`tests/test_ipv6_entrypoint.py` は既定Claude経路の挙動を維持する。新規Codex経路テストではpreflightモードも明示し、ログ分離とIPv4/IPv6失敗時の停止を確認する。新labelはc3c機能のprotocol名として `io.c3c.codex-audit-protocol` を維持し、Dockerfileでは既存labelと同じCACHEBUST消費RUNより後へ置く。

### Task 1: 起動時MCP helper

- [ ] 新規テストでnative一覧fixtureの正規化・比較を先に書く。Expected command/args/env/cwd/有効化変更でhashが変わる、key順とauth_statusだけの変化では変わらない。
- [ ] enabled helper、未知transport、不正型、truncated JSON、空stdout、非0、timeoutが起動不可となるテストを先に赤で確認。
- [ ] 実装し、`python3 -m unittest discover -s tests -p 'test_codex_mcp_audit.py'`。Expected 全成功。runtimeの動的実行をmockの成功だけで保証しない。
- [ ] 固定無認証imageのlocal plugin fixtureで、user/projectの競合解決とplugin由来stdioをnative一覧で確認。markerを使い一覧取得でcommand/helperが起動しないことを観測する。Expected 審査対象とnative設定済みMCPが一致。未解決ならhelper採用を確定しない。

### Task 2: launcherと承認台帳

- [ ] option parser、未知/重複/欠落、clean併用、envによる選択・台帳差替え、初回/同一/変更/拒否/TTY無しを実物launcherの隔離fixtureで赤にする。
- [ ] `--agent`/`--read-only` を追加。CodexでCODEX_DIR未指定を診断。既存Claudeと同じproject/image単位を使い、第2/3段階の識別子整理を混ぜない。
- [ ] support-label guard→preflight→host承認→本起動を組む。旧image/label欠落/未知値ならcontainer runゼロ。image不在/存在と`-b`有無の4組を検証し、必要な明示build後に対応imageが確認できた場合だけ通す。preflight失敗なら本起動を呼ばない。引数のshell再解釈はせず配列を使う。`--clean`/`--clean-all`/`--check`と既存清掃fixtureを拡張し、両agent・複数版の対象project記録だけを清掃することを確認する。
- [ ] `TMPDIR=/tmp ./test-build.sh --launcher-only`。Expected 既存と新規全成功、default Claude不変、`--check`で起動・書込みなし。

### Task 3: entrypoint・Compose・image配線

- [ ] dummy CLIとfake helperで、Claudeは共通初期化→既存gate→secret配線→exec、Codexは共通初期化→固定home/CLI実体→secret配線→audit/verify→execの順、unknown agent拒否、verify失敗時native CLIを呼ばない回帰を先に赤にする。
- [ ] preflightと本起動はfirewall後・同一secret export後にsnapshot/verifyする。`secrets/export/CODEX_HOME` に異なるMCP入りhomeを指定する回帰を追加し、全段階で固定homeが使われ未審査markerが動かないことを確認する。home/cwd/設定解決用override/CLI実体を三段階で比較する。一般のMCP用秘密は引き続き使用可能にする。末尾は固定絶対パスのCodex実体をexecし、固定argv `--sandbox workspace-write --ask-for-approval on-request -c ...` またはread-onlyへ分岐。Claudeは従来のargv。
- [ ] Codex未導入・未知版をfallback無しで診断。固定helperをstaging/asset hash/Dockerfileへ加え、対応labelをimageに付ける。許可済みhashのmountは`:ro`必須。固定preflight overrideも登録し、実物の非TTY経路でstderrログがprotocolへ混入しないこと、stdinを要求しないことを確認する。
- [ ] `./lint.sh`、`./test-build.sh --validator-only`、launcher-only、同梱hook回帰、該当Pythonテストを実行。Expected 全成功、Compose検査をskipで合格扱いにしない。

### Task 4: 実image受入

- [ ] `./test-build.sh --build-only` と本プロジェクトの変更箇所に必要な実機リビルド。Expected 新helper/entrypointがimageに入り、asset driftが解消。
- [ ] 実物launcherでdefault Claude/Codex選択・read-only、初回MCP承認/同一省略/変更再確認/拒否/未知helper拒否を確認。command markerを使い承認前に起動しないこと、readonly台帳を書けないことを確認する。
- [ ] 既存runtime手順でcapability・IPv4許可/拒否・保護ホスト設定・refreshを確認。Composeの保護に触れた場合は `./test-build.sh --config-ro-only`。Expected 既存境界維持。
- [ ] 専用ChatGPT認証でCodexの対話作業1件→停止→再開。ホスト設定/認証は共有しない。期限切れrefreshを観測できなければnot runとして残す。認証ありpreflightをcold/warmで計測し、cloud取得/HTTP discoveryがある条件と通信拒否時の終了を記録する。
- [ ] repo側hookがnativeの個別trust promptを通ることを確認し、個別UI登録後、最初の作業turnまで行いmarkerを確認する。変更後未承認→再登録を同条件で比較する。CLI起動だけの0B-8/9を実行成功の代用にしない。
- [ ] 指示/skill/memory/履歴/vaultの読み書き、Claudeの既存起動を確認。未実施は理由付きnot run、実装完了と日常利用受入を分ける。

### Task 5: 文書・レビュー・引渡し

- [ ] READMEへ操作、専用home、新規ChatGPTログイン、対応版/対応MCPと判定不能時拒否、起動時とruntimeの境界を同じ変更で記載する。SECURITY-CLAIMSは審査範囲・対象外・残余を対応付ける。ログイン手順・必要な許可ドメイン・callback方式は第0B-4の成立手順と今回の実機結果に照合し、未検証のport公開やドメインを推測で追加しない。
- [ ] セルフレビューと独立レビュー。Critical/Importantを全解消し、修正後確認限定巡。Codex実装の場合はPR前にclaude-reviewを使う。PR作成の承認範囲は別途守る。
- [ ] 日常利用は安全受入後に2project×5sessionの案を具体化する。移行タグはインターフェース追加のSemVer案を根拠付きで提案し、自動付与しない。

## 失敗時とロールバック

選択値不明、native起動失敗、設定不明、審査不能、承認拒否、二重照合不一致は停止。Claudeへfallbackしない。独立した実装branchの変更を戻せば旧Claude起動を維持できる。Codex専用homeの認証/履歴を消す操作はロールバックに含めない。既存のClaude承認台帳を新形式に上書きしない。

## レビューと実装者

計画レビューの履歴は以下に保存する。実装方法はsuperpowers:executing-plans（inline）。2026-09-21 の継続では、利用者が承認した Codex による実装・検証を専用worktreeで引き継ぐ。製品のレビューは現行 claude-review に従い、PR 前に Opus で 1 回、確認限定は同じ session の resume で計 3 巡までとする。以前の日付指定による途中レビュー再開は行わない。

2026-09-20時点: Codex独立レビューのCritical/Importantは修正し、確認限定巡で0件。Opusの初回レビューは900秒でタイムアウトし、出力なし（exit124）のためnot run。短い応答確認は成功したが、計画と関連コードを直接渡した範囲限定の再レビューも240秒でタイムアウト・出力なし（exit124）。原因は未確定。この時点では計画確定条件は未達だった。後続のFableレビューで補完した。セルフレビューで、三段階の比較対象を設定解決用overrideへ明確化し、execするCLI実体も固定絶対パスと明記した。Opusレビュー再実行時はこの改訂版を対象にする。


Fable初回レビュー（実効モデルclaude-fable-5-1）: Critical 0 / Important 6 / Minor 8。上記補足契約と各Taskに反映し、Fable確認限定巡（実効モデルclaude-fable-5-1）でCritical 0 / Important 0 / Minor 0、実装着手可。M-1の接頭辞統一案とM-2のHTTP URLをhashへ追加する案は採らず、c3c protocolの命名とローカルcommand審査の範囲を維持する理由を明記した。その他のMinorも計画上の具体化へ反映。実装・実測済みを意味しない。

実装: Opus — 起動時承認、マウント、認証を扱うセキュリティ境界の変更であり、コンテナ内実測も必要なため。実装開始時に実効モデルと専用worktreeを確認する。
