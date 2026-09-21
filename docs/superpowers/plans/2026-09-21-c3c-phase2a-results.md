# c3c 第2a段階の実装・検証記録

2026-09-21 作成・同日更新。[第2段階計画](2026-09-21-c3c-phase2.md) の Task 1（`c3c` 入口と引数解釈）・Task 2（CLI 選択の記憶と実起動配線）の実装、fake Podman による回帰検証、独立レビューへの対応、実 Podman・実認証での対話受入を記録する。

対象は `e0fdb322925e703eab70a508d202ff9ba66c2d47`（PR #133 マージ）を基点とする `c3c/phase2a-launch` worktree の差分。実装・レビュー・検証はコミット前の差分に対して行った。公開時の対象 SHA は PR 本文に記録する。

## 実装

- `c3c`: `claude-container` への symlink（新規）。呼出名 `${0##*/}` が `c3c` のときだけ新 parser（サブコマンド `claude`/`codex`、`--` 以降は位置引数、未知オプション exit 2、通常起動の dir 省略は `.`）を使う。旧入口の parser・解釈は変えない。
- `claude-container`: `RUN_DIR` を実ファイルまで symlink を辿って解決（`resolve_launcher_path()`。旧方式は相対リンクを別 cwd から呼ぶと別ディレクトリを基点にしていた。旧入口にも及ぶ改善）。`finalize_agent()` で `AGENT`/`READ_ONLY`/`CC_*` の readonly と export を各 dispatch 経路で 1 回に集約。c3c の通常起動は `freeze_agent_preference_key()` → `select_c3c_agent()`（明示 → 記憶 → `/dev/tty` の初回選択）→ `finalize_agent()` を対象ディレクトリ解決後・`load_env_file()` 前に行う。本起動を `run_main_compose()` に包み、`run_rc=0; run_main_compose || run_rc=$?` の後、rc 0 かつ c3c のときだけ `write_agent_preference()`、`exit "$run_rc"`。
- `agent-preference.py`（新規、ホスト専用）: `key`/`read`/`write`。Git common directory（非 Git はパス）の実体から sha256、strict JSON、`O_NOFOLLOW` の読込、同一ディレクトリ mkstemp → 全 byte 書込 → fsync → `os.replace` の保存。`GIT_*` を子プロセスへ渡さず、system/global 設定を無効化。
- `tests/test_agent_preference.py`・`tests/test_c3c_launch.py`（新規）、`test-build.sh` の `--launcher-only` へ登録、README「c3c 入口」節と「使い方」「アーキテクチャ」「前提」「変更後の確認」、`docs/development-invariants.md`、root `AGENTS.md` の対象ファイル一覧。

## 回帰検証（fake Podman、実 Podman 不要）

いずれも 2026-09-21 にホスト（Python 3.14.7、Git 2.53.0、bash 5.3.15、shellcheck 0.11.0）で実行。レビュー対応後の最終値。

| コマンド | 結果 |
|---|---|
| `python3 -m unittest discover -s tests -p test_agent_preference.py -v` | 29/29 成功（helper 不在で失敗することを先に確認。レビュー対応の 3 件は元実装で失敗することを先に確認） |
| `python3 -m unittest discover -s tests -p test_c3c_launch.py -v` | 38/38 成功（`c3c` 不在で 37 件中 failures=61 errors=1 を先に確認。旧 RUN_DIR 解決の相対 symlink ケースも単独で失敗を確認） |
| `python3 -m unittest discover -s tests -p test_codex_launch.py`（旧 suite、無変更） | 32/32 成功 |
| `TMPDIR=/tmp ./test-build.sh --launcher-only` | PASS 252 / FAIL 0（新 2 suite を含む。親による基点のホスト再実行は 250/0、実装・修正後の 252/0 は Opus 実装セッションで確認） |
| `./test-build.sh --validator-only` | PASS 82 / FAIL 0 |
| `./lint.sh` | OK（対象 15 本、`c3c` と `claude-container` の両方を検査、警告 0、Compose 検証はホストの podman-compose で実行） |

新 suite の主な検査: 絶対・相対・2 段 symlink、PATH 経由、`bash ./c3c`、dangling link の明示エラー、旧名の相対 symlink。表4 の全入力、空白を含む dir、`./codex`・`-- codex`、未知オプション、同値を含む agent 重複、dir 2 件、旧入口の寛容な解釈と `.` 非置換。専用 PTY の初回選択（1/2、不正値、EOF、Ctrl-C=130、空白許容）、非 TTY で即 exit 2（stdin の `1` を読まない）、記憶の採用表示、不正記憶の WARNING → 初回選択、明示指定の優先、記憶した Codex がガードで使えないときの再選択案内。本 run rc=17 で 17 を返し旧値維持、build・preflight・承認拒否・初回選択後の build 失敗で無更新、保存失敗で WARNING と rc 0、`--check`/`--clean`/旧入口で記憶を読まない・書かない・消さない、project env による保存先・値の変更不可、python3 不在と診断不能 Git での明示/無指定の分岐、linked worktree・サブディレクトリの共有と別 clone の分離、継承 `GIT_DIR` の無視。helper は main/linked/symlink/サブディレクトリの同一キー、別 clone・移動後の別キー、非 Git の path 単位、壊れた gitfile・壊れた linked worktree・権限不足・非空で `HEAD` の無い `.git`・dangling `.git` symlink・FIFO の rc4、空 `.git` の無視、strict JSON（重複 key・bool schema・4096 byte 超・symlink・FIFO を待たない）、read の無書込、write の 0700/0600・同時書込・書込不能・`RLIMIT_FSIZE` による短い書込で旧文書維持。

秘密不要の隔離 probe: podman 5.8.6 / podman-compose 1.6.0 で `docker.io/library/debian:stable` を `network_mode: none` の使い捨て service として `run --rm -T` し、container の `exit 0/17/130` が compose run の rc としてそのまま返ることを確認（実装側の観測。親側も既存製品イメージの ENTRYPOINT を維持して CMD を exit へ置換した別 probe で同じ rc 伝播を確認）。

## 独立レビューと対応（2026-09-21）

Codex（GPT-6 Astra、製品ファイルの変更なし）による独立レビュー。判定は Critical 0・Important 0・新規 Minor 4（既知の Minor 3 件は重複計上せず）。レビュアーが見なかった範囲: 実認証・ユーザー設定・他 worktree・`.claude` の証跡。実 Podman 対話受入・全体 suite・lint はレビュアー側では not run（実装セッションと親の検証との重複回避）。レビュー開始時・終了時の差分 hash（`git diff --binary` = 644b29ce…）は一致し、レビュー中の製品変更なし。

親セッションは元の Minor 1・2 を、計画第4節の明示契約（「別 repo の記憶を採用しない」「部分書込なし・失敗時は旧文書維持」）を破るとして should-fix に再分類した（元判定は変更していない）。対応:

| 元判定 | 内容 | 親の再分類 | 対応 |
|---|---|---|---|
| Minor 1 | 非空で `HEAD` の無い `.git`・dangling `.git` を無視し、Git と同じく外側 repo（または path）へ辿って別の記憶を採用する | should-fix | 修正。`has_git_ancestor()` は空の `.git` ディレクトリだけを無視し、dangling symlink・非空で `HEAD` 欠落・非ディレクトリ・調べられないものは診断不能（rc4）にする。回帰: `test_nested_repo_with_incomplete_git_directory_is_undiagnosable_not_outer_repo`（元実装では外側 repo と同じキーで rc0）、`test_dangling_or_non_directory_git_entry_is_undiagnosable`（元実装では path 単位で rc0）。正常 nested・linked・非 Git・空 `.git` は維持 |
| Minor 2 | `os.write()` の戻り値を見ず、短い書込を成功扱いして旧記録を破損する | should-fix | 修正。`write_all()` で全 byte を書き終えるまで反復し、進まなければ失敗。`SIGXFSZ` は `write` 実行時に明示的に無視して `EFBIG` を通常の失敗にし、一時ファイルを除去して rc1 を返す。回帰: `test_short_write_under_file_size_limit_keeps_old_document`（helper 子プロセスに `RLIMIT_FSIZE=10` を与える実 OS 再現。元実装では rc0 で記録が `{"schema":` に置換されることを先に確認） |
| Minor 3 | read の state directory がアクセス不能なとき rc4 でなく traceback/rc1 | 保留 | launcher は非 0 を同じ WARNING → 初回選択の分岐へ送るため実利用の差は診断文言のみ。スコープを広げず記録保留 |
| Minor 4 | state 自体が symlink のとき read は採用・write は拒否で非対称 | 保留 | 保存先の付け替え拒否は pref directory とファイルで担保しており、更新時に WARNING が出る。記録保留 |

修正後、同じ Codex レビュアーが元の指摘2件に限定して再確認した。破損 Git は rc4・stdout 空、短い書込みは rc1・旧文書維持・一時ファイルなしを再現確認し、should-fix の残件は0。

自己レビューの既知 Minor 3 件（再選択案内のパス未 quote、`bash c3c` のスラッシュ無し名、`~/.local/state` 不在時の write rc1）も記録保留のまま。

## 実 Podman・実認証での対話受入（2026-09-21）

持ち主の明示承認（既存のコンテナ用認証設定を使う）の範囲で実施。詳細な環境・残留資源・生ログは非公開の検証記録に保存し、ホストの個人パスや認証情報を公開側へ転記しない。

- 環境: 一時 HOME と一時利用側 project（`node-version.txt`=24.18.0、`codex-version.txt`=0.155.1、`allowed-domains.txt`=chatgpt.com・auth.openai.com、`env` に既存製品の Claude 認証の基点 `CLAUDE_CONFIG_DIR` と既存の専用 `CODEX_DIR`）。`CODEX_DIR` が実 `~/.codex` と別実体であることを `-ef` と `pwd -P` で確認。一時 HOME により rootless Podman の storage も隔離され、ホストの image/container/network は不変。既存 image に audit label が無かったため、一時 project 向けに `c3c claude -b` の通常経路で image をビルド（label `io.c3c.codex-audit-protocol=1`）。CLI 版は Claude Code v2.1.278、Codex v0.155.1。観測は実 podman をそのまま呼ぶ rc 記録 shim と、stdin/stdout/stderr を専用 pty にする harness。
- 結果（compose run rc / launcher rc / 記憶 JSON）:

| 操作 | rc | 記憶 |
|---|---|---|
| `c3c claude` → Bypass Permissions 受諾 → `/exit` | 0 / 0 | `claude` 新規作成（dir 0700 / file 0600、キーは `agent-preference.py key` と一致） |
| `c3c`（無指定）→ `INFO: 前回の選択: claude` → Ctrl-D、0.4 秒後に Ctrl-D | 0 / 0 | `claude` 再書込 |
| `c3c codex` → `/quit` | preflight 0、本 run 0 / 0 | `codex`（MCP のローカル command 定義 0 件 → 空定義を自動記録。任意コマンドの承認なし） |
| `c3c` → `INFO: 前回の選択: codex` → Ctrl-C、0.5 秒後に Ctrl-C | 0 / 0 | `codex` |
| `c3c codex --read-only` → `/quit`、`c3c --read-only`（記憶 codex） | 0 / 0 | `codex`。起動中の `podman exec ps` で `codex --sandbox read-only …` を確認 |
| `c3c claude --read-only` | — / 2 | 不変 |
| 初回試行（`-b` ビルド後、受諾ダイアログで harness の待機不一致 → 実装セッションが harness 側を誤って SIGTERM） | （未記録） | 未作成（中断 → 無更新） |
| `c3c`（記憶 claude）→ Ctrl-D を 2 秒空けて 2 回（Claude は「Press Ctrl-D again to exit」を表示して起動継続）→ 親セッションが別試行のつもりで実行した `podman stop --time 3` | 143 / 143 | 不変（外部停止。通常終了の判定から除外） |

- 判定: Claude（`/exit`、Ctrl-D ×2 連続）・Codex（`/quit`、Ctrl-C ×2）の双方で通常終了 rc 0 → 記憶更新の経路が成立。非ゼロ・引数エラー・中断では記憶が新設・変更されない。計画 Task 2 の「通常終了で記憶できる経路が一つも無ければ再設計」の条件には該当しない。
- 観測事項: Claude の「Bypass Permissions mode」受諾は起動ごとに出る既存の UI で、受入後も `.claude.json` の当該フラグは永続化されなかった。Claude の Ctrl-D は短い間隔で 2 回押す必要があり、2 秒空けると 1 回目として扱われる。
- ホストへの影響: 意図しない変更なし。CLI 標準動作の範囲で Claude の `.claude.json`・`~/.claude/projects/` の履歴、`CODEX_DIR` の sessions が更新された（認証の表示・複製なし）。
- 対象外（完了扱いにしない）: 日常利用 2 project × 5 session、認証 refresh、`/resume`、複数セッションの同時起動、実モデルへの作業依頼。

## 判断の記録（計画からの差分）

- 祖先 `.git` の判定は「gitfile か `HEAD` を持つディレクトリ」を「あり」、空の `.git` ディレクトリだけを無視（実装ホストの `/tmp/.git`（空）で全 fixture が診断不能になる事象から発見）。レビュー対応で、それ以外の異常（dangling・非空で `HEAD` 欠落・非ディレクトリ・権限不足）は Git が外側へ辿る前に診断不能にする。
- helper はディレクトリの mode を新規作成時だけ 0700 にし、既存の mode は変えない（毎回 chmod すると「書込不能で旧文書維持」の契約を自分で壊す）。
- helper の `write` は `SIGXFSZ` を無視して `EFBIG` を失敗として扱う（強制終了では一時ファイルの除去と rc1 の報告ができない）。
- c3c の `--clean <dir>` も dir 2 件以上は exit 2（計画は通常起動だけを明記。旧入口は 2 件目以降を無視する）。
- 初回選択の入力は前後の空白を落として `1`/`2` と比較（`1 2`・`12`・`0` は exit 2）。
- 記憶した CLI の再選択案内は `guard_codex_agent()`・`guard_codex_image_support()` の失敗に限る（CLI に無関係なガード、preflight 失敗、承認拒否では出さない）。
- 記憶の書込は memory 由来で同値でも本 run 正常終了ごとに行う（「最後に正常終了した CLI」を素直に保つ）。
