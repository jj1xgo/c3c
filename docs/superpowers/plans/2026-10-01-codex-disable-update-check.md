# #183 Codex 対話起動時の更新確認の無効化

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `c3c codex` の更新確認を無効にし、版の更新を `-b` の再ビルドで行う。

**計画者:** Opus 5.5。進行役が計画の調査結果に一次情報を補い、実装手順を以下に整理した。Opus の最終出力のモデルは transcript の `.message.model` で確認した。

**要件:** [#183](https://github.com/jj1xgo/c3c/issues/183)。`latest` はビルド時点の最新版であり、後日新版が出たときの起動時更新確認は止めない。

## 方針と範囲

`entrypoint.sh` の Codex 本起動に `-c check_for_update_on_startup=false` を追加する。既存の sandbox・approval・trust override の値と順序を維持し、新しい指定は trust override の後へ置く。利用者の設定ファイルは書き換えない。

対象は `entrypoint.sh`、`tests/test_codex_entrypoint.py`、`README.md`。`codex-launcher.sh` は変更しない。Claude 経路などから直接 `codex` を呼ぶ場合への指定追加は対象外。更新抑止は利便性の設定であり、新しいセキュリティ不変条件にはしない。

## 一次情報

- [公式設定リファレンス](https://developers.openai.com/codex/config-reference) は `check_for_update_on_startup` を boolean として定義し、更新を一元管理する場合に false にする設定としている。
- [rust-v0.159.3 の updates.rs](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/tui/src/updates.rs) の `get_upgrade_version` と `get_upgrade_version_for_popup` は、false の場合に更新確認・ポップアップ処理より前で戻る。npm 配布の release ビルドが対象で、debug build の挙動の根拠にはしない。
- [同版の updates_cache.rs](https://github.com/openai/codex/blob/rust-v0.159.3/codex-rs/tui/src/updates_cache.rs) は `CODEX_HOME/version.json` に `latest_version`・RFC3339 の `last_checked_at`・任意の `dismissed_version` を保存する。キャッシュの確認周期は20時間。取得は background で、失敗時はキャッシュを書かない。そのため「キャッシュが作られない」だけでは抑止成功を判定しない。
- ローカルの `codex --help` は `-c` の値を TOML として解析すると説明している。

## 実装手順

1. branch・差分・worktree を再確認し、`docs/development-invariants.md` の entrypoint の該当節を読み、他セッションの未追跡ファイルに触れず、分岐元 commit を記録した専用ブランチ／worktree を用意する。不変条件は CLI 実体・home・cwd・trust override を固定する既存要件であり、本変更はその条件を変えないので同文書は改訂しない。
2. 既存 `RunTests.test_run_verifies_then_execs_fixed_argv` の期待する argv の末尾へ `'-c', 'check_for_update_on_startup=false'` を追加する。通常・read-only 両方を既存 subTest で確認する。
3. `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_codex_entrypoint.py'` を実行。Expected: 本起動の2 subTest が新しい argv の欠落で失敗する。
4. `entrypoint.sh` の最終 exec の末尾へ `-c 'check_for_update_on_startup=false'` を追加し、直前に `# 起動時の更新確認は無効にする（#183）。版の更新は -b の再ビルドで行う。` を追記する。
5. README「アーキテクチャ」の固定 argv を更新し、「イメージの変更」に、対話起動での更新確認の抑止、更新方法 `-b`、latest の解決時点、旧イメージには再ビルドが必要なこと、直接呼び出しには付かないことを記載する。固定版を指定している場合は `.c3c/codex-version.txt` の版を変更してから `-b` を実行する。README「変更後の確認」に Codex の起動引数を変更したときの確認手順を追加する。設定の優先順位や未知の版の挙動について未確認の保証を書かない。
6. 起動テスト、`./lint.sh`、`./test-build.sh --launcher-only` を実行する。Expected: 全件成功、lint の終了コード0・警告0。sandbox が Podman を制限した場合は許可を得て host で再実行し、スキップを検証成功扱いしない。

README の確定文面（手順5）:

- 「アーキテクチャ」の既存 Codex 固定 argv の末尾に `-c 'check_for_update_on_startup=false'` を追加する。
- 「イメージの変更」の Claude 自動アップデートの段落直後へ、次の段落を追加する。

> Codex CLI の対話起動（`c3c codex`・`--agent codex`）では、`entrypoint.sh` が `-c 'check_for_update_on_startup=false'` を渡して起動時の更新確認を無効にする（[#183](https://github.com/jj1xgo/c3c/issues/183)）。版の更新は `-b` の再ビルドで行う。固定版を指定している場合は `.c3c/codex-version.txt` の版を変更してから再ビルドする。`latest` はビルド時点の最新版を入れる指定で、起動するたびに最新版へ更新するものではない。既存イメージへの反映には再ビルドが必要で、境界アセットのドリフト WARNING が案内する。この引数は c3c の本起動でだけ渡すため、ログインシェルや `podman exec` から対話 `codex` を直接起動する場合には付かない。

同段落末尾に、受入成功後に限り `確認した版: codex-cli <実イメージ版>・0.156.0。` を加える。0.156.0 は README に既存の確認記録がある固定版であり、この変更でも受入対象に含める。失敗・未実施なら該当版を確認済みとは書かず、理由を結果記録へ残す。

- 「変更後の確認」の Claude 起動引数の段落直後へ、次を追加する。

> `entrypoint.sh` の Codex 本起動の引数を変更した場合は、`tests/test_codex_entrypoint.py`（`--launcher-only` に含む）、`-b` の再ビルド後の実起動、`podman top <container> pid,args` による通常・read-only の実 argv、旧イメージに対する起動時と `--check` のドリフト WARNING を確認する。更新確認の抑止は argv の一致だけで判断せず、使い捨ての専用 home と同一の更新キャッシュを使い、本起動では更新案内が出ず、同じイメージから直接起動した対話 CLI では出る対照で確認する。既存の認証 home のキャッシュは書き換えない。Codex 0.156.0 を固定した fixture でも起動と抑止を確認する。未実施の項目は `not run` と理由を報告する。

## 実機受入

実施可能な host で、他セッションのイメージや設定を上書きしない専用 fixture を使用する。認証情報を表示・解析・自動コピーしない。

- 実イメージの Codex 版を確認し、その版の upstream source と更新抑止条件・キャッシュ形式を照合する。上記0.159.3と異なる場合は対象版を記録する。
- 旧イメージのまま変更後の launcher を使い、起動時と `--check` のドリフト WARNING を確認する。
- `-b` で再ビルドして起動し、`podman top <container> pid,args` で通常・read-only の実 argv と更新抑止指定を確認する。
- fixture の使い捨て `CODEX_DIR` に、直近時刻・`latest_version: "999.0.0"`・`dismissed_version: null` の有効な `version.json` を用意する。false 側は疑似端末から `c3c codex <fixture>` の本起動を通す。同じイメージの true 側は独立した使い捨て home をコンテナ内に用意し、`podman exec --user node -it <container> env CODEX_HOME=<別home> codex -c 'check_for_update_on_startup=true'` を疑似端末から実行する。両側で同一内容のキャッシュを試行前に復元し、user/project の設定は空にする。Expected: true 側で更新案内が出て、false 側では出ない。両側で試行後の `dismissed_version` と `last_checked_at` を記録し、dismissal または20時間経過による background 更新が対照を汚していないことを確認する。更新の実行には同意しない。認証情報は表示・解析・コピーしない。ログイン前に案内が出ないなど対照が成立しない場合は、この確認を不成立と報告し、成功とは書かず計画側へ戻す。新しい観測方法を実装者が設計しない。
- README に既存確認記録がある Codex 0.156.0 を pin した別 fixture を `-b` でビルドする。同版 upstream の更新処理とキャッシュ形式を照合し、同じ通常・read-only の起動と TUI 比較を行う。Expected: 新しい `-c` を渡して起動でき、更新案内が抑止される。互換性に問題があれば実装を確定せず、対応版下限・移行診断が必要か計画側へ戻す。

上流コードの確認、argv の fixture、実 argv、実 TUI の抑止効果を区別して報告する。実測ができない項目は `not run` と理由を記載し、確認済みとしない。Dockerfile を変更しないため全ビルド組合せの追加検証は要求せず、最終イメージの再ビルド・起動で確認する。

## レビューと公開

計画レビューは、作成に関わっていない Codex と Claude の二重で行う。Codex は持ち主指定により `codex exec --model gpt-6-astra --sandbox read-only` を先に background 起動し、stdin を `/dev/null` で閉じる。Claude は別の `--model opus` セッションで `claude-review` の計画レビュー手順を使う。実効モデルを記録する。

実装者の持ち主指定を受けてから編集する。境界のため PR 前の二重レビューを行い、Critical・Important に対応する。commit・push は既存の承認範囲に従い、未承認なら検証済み差分を提示して承認を求める。PR 作成後は別の Claude 対話セッションへレビューとマージを引き継ぐ。既定の挙動変更なのでタグ番号は実装後に SemVer 基準で提案する。

## Codex 実行条件

`workspace-write` と Podman・レビューに必要な host の許可／ネットワーク。上流コードの照合とレビューにはネットワークが必要。通常の編集と fixture テストには不要。`/goal` は持ち主が明示した場合だけ開始する。

渡す文面: 「#183 の本計画を executing-plans で実装する。通常・read-only の対話起動で更新確認を止め、README と既存テストを更新する。他セッションの変更に触れず、必要な lint・launcher テスト・実機受入を実施し、未実施項目を明記する。境界の PR 前二重レビューまで進め、未承認の commit・push は行わない。」

区分: 境界 — sandbox・approval・trust override を含む本起動の固定 argv に直接触れるため、保守的に重い区分を採る。抑止設定自体をセキュリティ境界と主張するものではない。

推奨実装: Codex — host の checkout で変更が完結し、追加する引数・テスト・README の範囲が確定している。秘密を読む経路や hook の変更はなく、独立した実機受入も host で実施する。

## 計画レビュー結果（2026-10-01）

- Codex: GPT-6 Astra（`gpt-6-astra`、reasoning `medium`。CLI の thread 記録で確認）、初回「実装に渡せる」。Critical 0・Important 0・Minor 2（固定版の更新手順、各 TUI 試行前のキャッシュ復元）は反映済み。
- Claude: Opus 5.5（json の `modelUsage` で確認）、初回「修正後に渡せる」。Critical 0・Important 3（旧版互換性の確認、TUI 比較の経路、逐語手順と推奨実装の根拠）を反映し、同セッションの確認限定1巡で全件解決・「実装に渡せる」。Minor 6も文面・配置・手順の補足に反映済み。
- 計2巡。レビューは静的な計画照合であり、実装・実機受入の成功を意味しない。未対応の Critical・Important・Minor はない。レビュー終了後に、この Codex セッションでの実装指定を受領した。

実装: Codex（持ち主指定、2026-10-01。このセッションで executing-plans）。

## 実装・検証結果（2026-10-01）

- 分岐元: `baa8eedc36f30c8e78fa3120f9b3c9ef595dac17`。専用ブランチ `fix/codex-disable-update-check`。他セッションの未追跡ファイルは変更していない。
- RED: 通常・read-only の2 subTestが末尾の設定欠落で失敗。変更後の同じ RunTests は5件成功。
- 最終 `./lint.sh`: sandbox 内では Podman の `/run/user/1000` 書込み制限で失敗。host 再実行で終了コード0・Compose を含め成功・警告なし。生ログは別々に保存した。
- host の `./test-build.sh --launcher-only`: PASS=451・FAIL=0。sandbox 内の結果は PASS=449・FAIL=2（socket 作成と Podman の制限）で、製品の失敗とは区別した。
- `./test-build.sh --validator-only`: PASS=82・FAIL=0。`bash examples/hooks/tests/test-block-pr-approve.sh`: 全ケース green。
- 専用 fixture の旧イメージ: 本起動で更新案内を再現。起動時と `--check` で境界アセットのドリフト WARNING、`--check` の集計は WARN=1・FAIL=0。
- 専用 fixture で `-b` 後の 0.159.3（latest 解決結果）と pin 0.156.0: 通常・read-only の4本起動が成功。`podman top` で sandbox・approval・trust override と末尾の更新抑止指定を確認し、更新案内が出ないことを確認した。
- 同じ再ビルド済みイメージごとの使い捨て home・直近時刻の `version.json` で、true は 999.0.0 への更新案内、false は案内なしでサインイン画面を表示。認証情報は持ち込まず、更新は実行しなかった。直接起動の TUI 対照では試行後のキャッシュの日時と dismissal は不変。本起動4本については毎回キャッシュを再作成したが、各試行後の値を個別保存しておらず、各版とも最後の read-only 起動後の値だけが残っている。
- Ruling: true の対照は `podman exec` の代わりに、同じイメージの起動口を `podman run --entrypoint /usr/local/bin/codex` で直接起動した。独立した home と同一のキャッシュ形式で比較でき、既存コンテナを操作する必要がないため。false の効果は別途 `c3c codex` 本起動と実 argv で確認した。取り違えのリスクは、直接起動だけで本起動の実測を代用しないことで抑えた。
- `test-build.sh --build-only` と引数なしの全体実行: not run（Dockerfile 非変更、専用 fixture の実リビルド・起動で今回の変更を確認）。GitHub CI: not run（未投稿）。

## PR 前レビュー結果

- Codex: GPT-6 Astra（明示指定、thread 記録で確認）。初回 With fixes、Critical 0・Important 1・Minor 0。最終 lint のログ不足に対し host 成功の生ログと記録訂正を提示し、確認限定1巡で解決・Yes。
- Claude: Opus 5.5（`modelUsage` で確認）。初回 With fixes、Critical 0・Important 1・Minor 4。同じ lint 指摘を確認限定1巡で解決・Yes。
- Minor の扱い: TUI 対照の `podman run` への変更は PR 本文へ記載する。本起動の各試行後キャッシュ値の保存不足は検証結果に限界として記載済み。他セッションの未追跡ファイルは add しない。0.156.0 より古い版の互換性は今回保証しない（対応不要との判定）。
- 製品の3ファイルは初回実装レビューから不変。未解決の Critical・Important はない。未コミットの固定差分をレビュー対象にした（持ち主の commit・push 承認は別途必要）。両レビュアーの全文と確認限定の結果は、PR 作成後にそれぞれコメントへ掲載する。
