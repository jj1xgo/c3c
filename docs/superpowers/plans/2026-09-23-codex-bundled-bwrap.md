# #145: Codex 同梱 bubblewrap 優先の実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

## 目的と状態

システム版 bubblewrap が画像ライブラリの間接依存として存在しても、c3c の通常 Codex 起動で同梱版を選び、Codex 自身の proc fallback により sandbox 内のコマンドを起動できるようにする。新しい procfs のマウントを成功させる変更ではない。要件は [#145](https://github.com/jj1xgo/c3c/issues/145)。基準は `b204b56`（v13.0.1）、対応 Codex は `0.156.0`。本書は設計と実装手順を併記する。2026-09-23、レビュー完了後に持ち主が「続けて」と承認した。その後「handoverで良いよ」と指定したため、実装は開始せず次の Claude セッションへ引き継ぐ。計画・実装者 Opus・推奨実行方法 executing-plans の承認は引き継ぎ、環境が求める権限やモデル切替の確認は別途満たす。

技術: Dockerfile、Node.js の標準モジュール、Bash、Python unittest、Podman。新しい実行時依存は追加しない。

## 根拠と設計判断

一次情報は対象版の [launcher.rs](https://github.com/openai/codex/blob/rust-v0.156.0/codex-rs/linux-sandbox/src/launcher.rs)、[bundled_bwrap.rs](https://github.com/openai/codex/blob/rust-v0.156.0/codex-rs/linux-sandbox/src/bundled_bwrap.rs)、[PATH 探索](https://github.com/openai/codex/blob/rust-v0.156.0/codex-rs/sandboxing/src/bwrap.rs)、[npm ラッパー](https://github.com/openai/codex/blob/rust-v0.156.0/codex-cli/bin/codex.js)、[proc fallback](https://github.com/openai/codex/blob/rust-v0.156.0/codex-rs/linux-sandbox/src/linux_run_main.rs)、[子の環境生成](https://github.com/openai/codex/blob/rust-v0.156.0/codex-rs/protocol/src/shell_environment.rs)。

- Codex は PATH 上の最初の候補を canonicalize し、cwd 配下を除外する。候補の help に `--as-pid-1` と `--perms` があれば System launcher として選ぶ。同梱優先の config キーはこの選択処理にはない。
- 同梱版の proc マウント失敗は `/newroot/proc` を含むため、`linux_run_main.rs` の検出に一致し `mount_proc=false` へ切り替わる。システム版 0.12.0 の `/proc` 表記は一致しない。fallback は外側コンテナの procfs を引き継ぐ。上流が secure default とする新しい procfs と同じ保護範囲とは扱わない。これはシステム版のない既存環境でも使われる上流の経路だが、外側プロセスの見え方とアクセス可否を Task 3 で確認する。
- ビルド時に `/usr/local/libexec/c3c/codex-bwrap/bwrap` を同梱実体への絶対 symlink として作る。ディレクトリ内はこのリンクだけ。実体は Codex の npm ラッパーと同じ解決順で選び、全 npm ツリーの glob 探索はしない。
- `entrypoint.sh` の Codex 専用分岐で、このディレクトリを PATH の先頭に加える。entrypoint が起動する snapshot、verify、Codex 本体には同じ PATH を渡す。Codex 内部は `shell_environment_policy` により子と sandbox helper の環境を再構成するため、同梱優先の受入は PATH を変更しない既定 policy を対象とする。`set.PATH`、`exclude`、`inherit` 等で PATH を変える設定は選択を変えうる対象外条件として文書化する。設定を強制上書きする機構は加えない。Claude の分岐とイメージ全体の `ENV PATH` は変えない。
- 常に同梱版を優先する。システム版の有無で分岐するとイメージごとに選択が変わるため採らない。同梱版が存在しない／実行不能ならビルドと Codex 起動を明示的に失敗させる。システム版への fallback は設けない。
- entrypoint の存在検査は欠落を早く明示するためのもの。上流では最初の候補の help が不適合なら Bundled 経路へ進み、次の PATH 候補のシステム版を再探索するわけではない。
- PATH 経由では上流の Bundled launcher が行うビルド時 digest との比較と `/proc/self/fd` 経由の exec を通らない（上流 digest 自体もビルド条件による）。c3c 独自の hash pin・起動時 checksum は追加しない。導入済みファイルから hash を計算して保存するだけでは配布元の独立した検証にならず、更新と監査対象を増やす。信頼は npm による配布物導入と root 所有のイメージに置く。実体・リンクの親を含め node が置換できないことをビルドと実機で検査する。root／イメージの改ざんは防御対象外。これは上流の digest 検証と同等の保証ではない。
- システム版を削除・移動せず、`/usr/bin/bwrap` を書き換えない。Codex 子プロセスから名前で `bwrap` を呼ぶと同梱版になるため、システム版が必要な呼出しは絶対パスを使う。glycin-loaders への実影響は受入で確認し、未確認なら保証しない。c3c 外の独立起動や `podman exec` には entrypoint の環境変更は自動適用されない。
- MCP stdio の `command = "bwrap"` も PATH の変更の影響を受ける例として説明する。承認記録にあるコマンド文字列と、解決される実体の区別を保つ。
- `codex-resources` 全体の PATH 追加、システム版の撤去、stderr の書換え、上流バイナリのパッチ、sandbox 無効化、`unmask=/proc/*` は採用しない。

## 共通制約とレビュー重点

`docs/development-invariants.md` の Dockerfile・entrypoint・Codex 審査の節を守る。firewall／capability／mount／MCP の境界を緩めない。秘密 export より前に固定 PATH を確定する。`CODEX_HOME`・CLI・cwd・trust override は現行と同じ。Codex opt-out の空ファイルは維持する。

重点となる入力と試験の担当:

1. npm の nested / hoisted / legacy vendor 配置、別アーキテクチャの混在 → Task 1。
2. optional package は解決できるが資材が欠落している場合 → 別の vendor に黙って切り替えず失敗、Task 1。
3. dangling link・非実行ファイル・不足した help オプション → fail-closed、Task 1・2。
4. PATH の上書き、snapshot と verify の差、Claude への漏出 → Task 2。
5. system bwrap が存在する実機、node による置換、子プロセスへの影響 → Task 3。

## Task 1: 同梱実体の解決とビルド時のリンク作成

対象: `Dockerfile.claude` の Codex install RUN と既存 ownership 再固定後の新しい RUN、`tests/test_codex_bwrap.py`（新規）、`test-build.sh` の launcher-only と build 検査。新しい製品 helper ファイルは作らず、短い Node スクリプトを新しい RUN 内で `node -e` として実行する。新規固定アセットの staging 経路を増やさない。

インターフェース: Codex install 成功後に固定リンクを作る。opt-out では作らない。失敗時は非ゼロでイメージを作らない。

- [ ] 先に Python fixture テストを作る。Dockerfile の一意な開始・終了コメントで区切った Node スクリプトを抽出する。埋込みはシェルの単一引用符で囲んだ `node -e` とし、JS の文字列リテラルは二重引用符へ統一する。抽出コードに単一引用符・ドル記号・バックスラッシュがないこと、外側引用符とマーカーが各一組だけあることをテストで要求し、独自の一般的な引用解除処理は書かない。Dockerfile の行継続だけを除いたコードを実行する。テスト用コピーの固定 CLI と出力ディレクトリだけを一時領域へ置換する。`process.arch` はテスト用コピーで `x64` / `arm64` / 未対応値へ置換する。ホストの `/usr/local` は触らない。ホスト Node の不在は明示失敗とし、最初の CI 実行で Node の版と試験結果を記録する。
- [ ] `node:module` の `createRequire`、`node:fs`、`node:path` で次の解決処理を実装する。エラー文は日本語、先頭 `ERROR:`。例外時は `process.exit(1)`。以下は処理の核であり、外側にエラー処理とリンク作成を加える。

```javascript
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");
const cli = fs.realpathSync("/usr/local/bin/codex");
const req = createRequire(cli);
const targets = {
  x64: ["@openai/codex-linux-x64", "x86_64-unknown-linux-musl"],
  arm64: ["@openai/codex-linux-arm64", "aarch64-unknown-linux-musl"],
};
if (process.platform !== "linux" || !targets[process.arch]) {
  throw new Error("対応していない Codex のアーキテクチャです");
}
const [pkg, triple] = targets[process.arch];
let vendor;
try {
  vendor = path.join(path.dirname(req.resolve(pkg + "/package.json")), "vendor");
} catch (error) {
  if (error.code !== "MODULE_NOT_FOUND") throw error;
  vendor = path.resolve(path.dirname(cli), "..", "vendor");
}
const target = path.join(vendor, triple);
const binary = fs.realpathSync(path.join(target, "bin", "codex"));
const bwrap = fs.realpathSync(path.join(target, "codex-resources", "bwrap"));
```

- [ ] `binary` と `bwrap` が通常ファイルかつ実行可能であることを検査する。realpath 後の bwrap が対象 target の実パス配下にあることも検査し、外部を指すリンクを拒否する。CLI の npm root を固定しないため nested・hoisted をともに扱える。解決できた package の資材が欠落した場合は catch の外で失敗させる。上流は resolve 時の全例外で legacy へ進むが、c3c は `MODULE_NOT_FOUND` だけに限定する意図的な安全側の差分である。
- [ ] `bwrap --help` を Node の `execFileSync`（timeout 5000 ms）で実行し、成功かつ `--as-pid-1`・`--perms`・`--argv0`・`--ro-bind-fd` の4項目を要求する。後ろの2項目により System launcher の古い版向け argv 変換を回避する。同梱版の版表示もログに残す。未知の将来版は自動で互換と扱わない。
- [ ] Codex install RUN では npm install のみを行う。解決・help 検査・リンク作成・ownership 検査を行う別 RUN を、既存の `chown root:root /usr/local/bin /usr/local/lib /usr/local/share` の後、`USER node` の前へ置く。別 RUN も空の codex-version.txt の場合は全処理をスキップする。固定ディレクトリを root:root 0755 で作り、絶対 symlink を作る。リンク・target ファイルと全親ディレクトリについて root 所有かつ group/other 書込不可を検査する（symlink 自体の mode 0777 は除外、親は除外しない）。新規 libexec 階層は所有者と mode を明示設定する。既存の npm 階層が不適合なら広い再帰 chmod で隠さずビルドを失敗させる。最終イメージの状態は build-only の実検査でも必須確認する。
- [ ] install とリンク作成の両 RUN で `set -e` を有効にし、それぞれ npm install と Node スクリプトの失敗が最終ステータスに伝播する構造にする。両 RUN とも `/tmp/codex-version.txt` を `tr -d '[:space:]'` で正規化した値を opt-out の判定に使う。空の分岐には Node を呼ぶ処理を置かない。
- [ ] fixture は nested・hoisted・legacy、x64・arm64 を成功させる。両配置がある場合は npm と同じ optional package が勝つ。未対応 arch、選択された package の bwrap 欠落、実行不能、target 外 symlink、help の4項目それぞれの欠落（`--argv0` と `--ro-bind-fd` も個別に検査）・非ゼロ・timeout は失敗させる。root ownership 検査は非 root fixture で偽装せず、次の実 build 検査で検証する。抽出テストは解決処理と help 検査の範囲を明示し、RUN 全体の検証と呼ばない。
- [ ] `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_codex_bwrap.py' -v` を実行する。実装前はスクリプト不在で FAIL、実装後は全成功を保存する。`test-build.sh --launcher-only` へ同じコマンドを追加する。
- [ ] build 検査へ固定リンク・版・owner/mode・実体が npm の対応 triple 内・専用ディレクトリがリンク一つのみの検査を追加する。空 Codex の既存実 build 試験に固定リンクも不存在であることを追加する。`./lint.sh`、`./test-build.sh --launcher-only`、`./test-build.sh --build-only` を実行し、各結果を保存する。

## Task 2: 審査と本起動への同じ PATH の配線

対象: `entrypoint.sh`、`tests/test_codex_entrypoint.py`、`README.md`、`docs/development-invariants.md`、`docs/codex-proc-investigation.md`。

インターフェース: 固定リンクを Task 1 が提供する。PATH は Codex 分岐でのみ一度 prepend し、以後 snapshot / verify / exec へ継承する。

- [ ] `tests/test_codex_entrypoint.py` の fixture に専用 bwrap ディレクトリを追加し、実 entrypoint の固定パスをその fixture へ置換する。既存 dummy の PATH 記録で、全 Codex 呼出しの先頭が専用ディレクトリ、残りが受取 PATH と同一であることを検査する。Claude recorder に PATH 記録を追加し、完全に不変であることを検査する。
- [ ] preflight、承認後の run、read-only の run で PATH 一致を検査する。`secrets/export/PATH` に別値を置いても変更されないこと、リンク削除・dangling・実行不能で審査 helper／CLI が一度も呼ばれず失敗することを追加する。CLI 自体がない opt-out の既存エラー文は保持する。
- [ ] 実装前に追加テストが FAIL することを確認する。Codex 固定 home / CLI の設定分岐へ次を加える。PATH 用の新しい秘密上書き可能な変数は作らない。

```bash
  export PATH="/usr/local/libexec/c3c/codex-bwrap:$PATH"
```

- [ ] CLI の存在検査の直後、snapshot / verify より前に固定リンクの `-f` と `-x` を検査する。失敗したら `ERROR: Codex 同梱の bubblewrap がありません。-b で再ビルドしてください。` を stderr に出して `exit 1`。preflight の stdout は protocol 専用のまま。ここでは root が保護するビルド済み資材を再探索・再生成しない。
- [ ] `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_codex_entrypoint.py' -v`、`./lint.sh`、`./test-build.sh --launcher-only` を実行する。Expected: 全成功、Compose を含む lint rc 0。
- [ ] README に同梱優先、システム版の保持、子の PATH 継承、独立起動と PATH を変える shell_environment_policy の対象外条件、root 所有を信頼する範囲、再ビルド手順を記載する。proc fallback の仕組みと新しい procfs との保護範囲の差も明記する。調査文書では #140 の当時の回避策を歴史として残し、#145 では依存パッケージを削除しないことを書く。実機の結果は Task 3 の後に追記する。不変条件に entrypoint が渡す範囲での snapshot / verify / exec の PATH 一致とリンクの保護を追加し、Codex 内部の環境再構成までは保証しない。

## Task 3: 実コンテナでの受入と引渡し

対象: `test-build.sh` の実 build 検査、README の変更後確認節、調査文書の受入記録。新しい test-build モードは追加せず、fixture は launcher-only、イメージ内検査は build-only と全体、対話受入は別途記録する。

- [ ] `./test-build.sh` 全体を実行し、Codex opt-out・Node opt-out の既存実 build を含めて確認する。未実行／環境による失敗と成功を区別する。
- [ ] システム bubblewrap のある受入用プロジェクトを用意する。対象の旧 image ID、c3c commit、Codex 版、`/usr/bin/bwrap --version`、package 依存を記録する。修正前は read-only の pwd と workspace-write の git status が `/proc` エラーで失敗することを同じホストで確認する。
- [ ] 修正済み c3c を使い、旧 image に対して `c3c codex --check <project>` が境界アセットのドリフトを検出することを確認する。`c3c codex -b <project>` で再ビルドし、通常 ENTRYPOINT と MCP 審査を通す。手元の画像用途プロジェクトを変更する場合は、その変更の承認範囲を別途確認する。隔離 fixture の利用なら他 repo の設定を書き換えない。
- [ ] 通常セッションのツールで `pwd`（`/workspace`）と `git status --short --branch`（rc 0）を確認する。read-only モードでも確認する。`command -v bwrap`・`readlink -f`・版表示を保存する。これだけを Codex 内部の exec 選択の証明にはしない。必要なら同じ受入イメージの診断複製で exec trace を採取し、bwrap 実体の選択を確認する（ptrace 等の追加権限が必要な診断は通常受入と区別し、その成功を境界の証明にしない）。
- [ ] 受入は PATH を変更しない既定 shell_environment_policy で行い、その条件を記録する。隔離設定で `set.PATH` が `/usr/bin:/bin` の場合も比較し、対象外条件で選択が変わりうることを確認する。利用者の既存設定は書き換えない。
- [ ] sandbox 内外で `readlink /proc/self/ns/pid` と `/proc` の PID 一覧を比較し、fallback による外側 PID の可視性を記録する。外側の node ラッパーと Codex の PID を特定し、sandbox 内から各 `/proc/<pid>/environ` と `cmdline` を O_RDONLY open できるかだけを確認する。内容や秘密値は読み出し・表示しない。読める場合は README のセキュリティモデルに観測した制約を明記し、既存の保証との矛盾があれば完了扱いせず持ち主へ判断を返す。読めない結果も当該プロセス・版に限定し、全プロセスの不可視性を主張しない。親の bwrap が proc 上で観測可能なら `/proc/<pid>/exe` の readlink も採取して、実際の選択の証拠にする（観測できるかは実測で判断）。
- [ ] node として固定リンク・各親・npm 実体を変更できないことを確認する。既存ファイルへの write/truncate は行わず、mode/所有者と `test -w` を保存する。`/usr/bin/bwrap` の実体・版がビルド前後で維持されることを確認する。
- [ ] read-only で workspace の既存ファイル、workspace-write で `/home/node/.gitconfig`、両方で proc の保護対象が O_WRONLY open を拒否することを確認する。`write`・`truncate` はしない。非特権 `iptables -S` は拒否、capability はゼロ、NoNewPrivs と seccomp を記録する。
- [ ] 通常コンテナの通信と内側 Codex の通信を区別する。通常コンテナで `api.github.com:443` の接続成功、`example.com:443` と `api.github.com:80` の接続失敗を確認する（上限時間を設定）。Codex のネットワーク制約で許可通信も止まる場合はコンテナ firewall の失敗と誤認せず、コンテナ側で別計測する。MCP の未承認・不一致が起動を拒否することも実 fixture で確認する。
- [ ] Claude の通常起動では PATH とシステム版 bwrap の選択が従来どおりであることを確認する。glycin-loaders の画像処理を、そのパッケージを利用する実際の入口から最小の画像で確認する。環境が用意できない場合は `not run` と書き、Codex 子プロセスからの画像処理まで互換と主張しない。
- [ ] README と調査文書に実測した版・image ID・結果・not run を記録し、`./lint.sh` を実行する。対応 Codex を将来更新するときの確認事項として、上記4つの上流ファイル、help の必要オプション、npm の配置、通常起動と通信／mount の受入を記載する。arm64 は fixture の合格と実機での合格を区別する。
- [ ] 実装のコミット／push／PR は既存の承認範囲と運用規則に従う。PR 前は `claude-review`、PR 後は別 Codex と Opus の独立レビューを行う。計画レビューで実装レビューを代替しない。必須受入が未完了なら #145 の解決済みとは扱わない。

## 計画レビューの記録

2026-09-23、Opus 5.5（`claude-opus-5-5`）が読み取り専用でレビューした。初回は Critical なし、Important 4 件と Minor 6 件。proc fallback の説明と受入、help の4項目、Codex 内部の環境再構成、ownership 検査順などを反映し、同じセッションで確認限定巡を実施。「実装に渡せる」、前回指摘はすべて解消との判定を得た。確認巡の軽微な注記に従い、両 RUN の `set -e` と同一の opt-out 判定も明記した。

実装後の最終レビュー（2026-09-23）で、上記「entrypoint の存在検査は欠落を早く明示するためのもの」は help が不適合な場合に限る記述と分かった。上流 `find_system_bwrap_in_search_paths()` は存在しない・実行できない候補を飛ばして次の PATH 候補を選ぶため、リンクの欠落・dangling・実行不能ではシステム版へ黙って戻る。entrypoint の検査はそれを防ぐ fail-closed として README・不変条件・entrypoint のコメントを訂正した。

これは計画の静的レビューである。製品実装・実ビルド・通常起動・境界受入は not run（計画作成の段階のため）。承認後も Task 1〜3 の実測と実装後レビューを省略しない。

## リリース判定と実行方法

想定は PATCH（現時点の候補 v13.0.2）。新しい設定機能の追加でなく通常 sandbox が失敗する不具合の修正で、利用側は再ビルドのみ。子の PATH 変更が利用側に非互換な移行を要求すると実測された場合は、PATCH の前提を撤回して持ち主へ判定を返す。タグは実装完了後に改めて提案し、承認なしで作らない。

計画の承認後、Claude は本書を Plan Mode で読み、`executing-plans` による一貫した実装を推奨する（ビルド・PATH・受入が連続するため）。Opus が選択されていなければ最初の編集前にモデル切替を案内する。実環境のネットワーク・Podman・sandbox の許可は別に満たす。計画時のレビュー記録は引渡し時に本書と併せて渡す。

実装: Opus — Codex の sandbox 選択と秘密 export 前の環境確定に触れる境界変更であり、実コンテナの通常起動・通信・マウント保護の受入までが必要なため。
