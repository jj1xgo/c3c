# Copilot CLI の opt-in を外す 設計

## 目的と理由

c3c は v20.x で、GitHub の Copilot CLI を command sandboxing 付きでコンテナに入れる opt-in（`.c3c/copilot-version.txt`）を持つ。これを作ったのは、保守者が Copilot CLI を独立のレビュアーとして使うためだった。その保守者が Copilot CLI を使わなくなったので、opt-in を丸ごと外す。

外す理由は、使わない境界機構を監査の対象に残さないため（root `AGENTS.md`「独自実装の追加は監査対象の拡大として避ける」）。起動口・bwrap の中継・sandbox の設定の雛形・ビルドの中の設定の読みの確認は、どれも c3c の独自実装で、Copilot CLI の版が上がるたびに canary で確かめ直す前提だった。使う人がいないまま残すと、確かめられない境界が残る。

## ゴール

- Copilot CLI に関わる c3c の実装・試験・文書を外す。既定のイメージ（opt-out）は今と同じ中身のまま（もともと Copilot は入らない）。
- 外した後に、利用側のプロジェクトの `.c3c/copilot-version.txt` に版が書いてあれば、起動と `--check` が止まり、ファイルを消すよう案内する（持ち主の決定。v16 で旧名の設定ディレクトリを廃止したときと同じ形）。
- 利用者から見えるインターフェースの削除なので SemVer の MAJOR（README「バージョニング」）。

## ゴールでないもの

- 作り直していない古いイメージを止めること（持ち主の決定）。古いイメージには Copilot が入ったまま残るが、いつもの資産のハッシュのずれの WARNING（`-b` で作り直すよう促す）に任せる。古いイメージを止めた v19・v20 は安全の欠陥を直すためで、今回は当たらない。
- GitHub MCP サーバ（`.mcp.json.example` の `https://api.githubcopilot.com/mcp/`）と、このリポジトリ自身の `.c3c/allowed-domains.txt` の `api.githubcopilot.com`。どちらも GitHub MCP のためで、Copilot CLI とは別物なので残す。
- 過去の計画と設計（`docs/superpowers/plans/` と `specs/` の Copilot の 8 本）。経緯の記録として残す（書き換えない）。
- `SECRETS_DIR` の `COPILOT_PAT` を c3c が消したり検出したりすること。不要になったことと、消してよいこと（失効は GitHub で）を README に書くだけにする。
- `HOME_MOUNT`・`HOME_MOUNT_RO`（#259）。Copilot のために足したが汎用の機能なので残す。

## 避けること

- 古い `copilot-version.txt` を黙って無視すること（Copilot が入ると思ったまま使われる）。
- Copilot を外すついでに、`bubblewrap` を使うほかの経路（Codex の同梱 bubblewrap、#145）を巻き込むこと。Copilot の区間で入れていた Debian の `bubblewrap` は Copilot だけのものだが、Codex の同梱 bubblewrap は別物で、変えない。
- 境界の不変条件（`docs/development-invariants.md`）の、Copilot と関係ない項目を巻き込むこと。

## 方式の検討

古い `copilot-version.txt` の扱い（持ち主が A を選んだ）:

- **A. 起動と `--check` で止め、消すよう案内する（採用）**: 利用者が必ず気づく。`--check` が移行作業を検出する（root `AGENTS.md` の要件）。前例は v16 の旧名の設定ディレクトリ（`guard_fail` で止めて案内）。費用は、ファイルを消すまで起動できないこと。
- B. WARNING を出して無視し、起動を続ける: 手間は無いが、見落とすと Copilot が入っていると思い込む。
- C. 黙って無視する: ファイルの意味が黙って変わり、fail-closed の方針に合わないので外した。

## 外すもの

1. ファイルを消す: `copilot-launcher.sh`、`copilot-bwrap-shim.sh`、`copilot-settings.json`、同梱の `copilot-version.txt`、`tests/copilot-canary.sh`、`tests/copilot_canary_helper.py`、`tests/fixtures/copilot-canary/`、`tests/test_copilot_bwrap_shim.py`、`tests/test_copilot_canary.py`、`tests/test_copilot_canary_helper.py`、`tests/test_copilot_config_check.py`、`tests/test_copilot_launcher.py`。
2. `Dockerfile.claude`: `# >>> c3c copilot` から `# <<< c3c copilot` までの区間と、その後にある、許可リストに Copilot の宛先を足す RUN。`test-build.sh` の、鍵を取り直す RUN の数の期待値（Copilot の層の分）と、apt-sources（#273）の不変条件・README にある「Copilot の層」の文言も直す。`ARG COPILOT_CACHEBUST` も区間の中。
3. `compose.yml`: build args の `COPILOT_CACHEBUST`。
4. `c3c`:
   - 版の解決と表示（`copilot-version.txt` の読み、`Copilot 版:` の行、Node が空で Copilot が有効なときの WARNING）。
   - ビルドの `COPILOT_CACHEBUST` の計算と受け渡し。
   - 資産の一覧（`ASSET_HASH_TARGETS`、境界アセットの case、ビルドコンテキストへの集約）から Copilot の 4 つのファイル。
   - `HOME_MOUNT` の秘密と認証の置き場との重なりの検査は残し、理由を書き直す（持ち主の決定。下の「`HOME_MOUNT` の秘密の検査の理由」）。
   - 新しい検査: プロジェクトの設定ディレクトリに `copilot-version.txt` があり、中身が空白以外を含めば、起動と `--check` で止める（下の「残った設定の検査」）。
5. `test-build.sh`: Copilot の 5 つの `check`（中継・Dockerfile の区間・起動口・canary の判定と段取り）、資産の写し、`--build-only` の「Copilot は既定で無効」の検査、実ビルドの opt-in の節。代わりに「残った設定の検査」の試験を足す。
6. ほかの試験の一覧から Copilot の名前を外す: `tests/test_c3c_launch.py`（`COPILOT_CACHEBUST`）、`tests/test_container_paths.py`、`tests/test_network_timeouts.py`、`tests/test_c3c_config.py`（Copilot の版の解決の試験）。`tests/test_install_apt_sources.py` と `install-apt-sources.sh` は、コメントの言及だけを直す。
7. `README.md`: 「Copilot CLI を使う」の節、利用側プロジェクトの設定の `copilot-version.txt` の行、「変更後の確認」の Copilot の行、そのほかの言及。代わりに、廃止したことと、残っていたら止まること・消し方・`COPILOT_PAT` は不要になったこと（失効は GitHub で）を短く書く。
8. `docs/development-invariants.md`: `copilot-bwrap-shim.sh`・`copilot-launcher.sh`・`copilot-settings.json`・Dockerfile の Copilot の区間の項。AGENTS.md の「変更する前に該当節を読む」の一覧に Copilot のファイルがあれば外す。
9. `.gitignore`: `.c3c/copilot-version.txt` の行とその説明。
10. `lint.sh` に Copilot のファイルを名指しする箇所があれば外す（無ければ何もしない）。

## 残った設定の検査

- 対象: プロジェクトの設定ディレクトリ（`$PROJECT_CONF_DIR`）の `copilot-version.txt`。
- 中身が空白（改行を含む）だけなら止めない（もともと「入れない」の意味だったので、意味が変わらない）。止めないが、消してよいことを `--check` で `[INFO]` として 1 行出す（実装者の判断に任せる。出さなくてもよい）。
- 空白以外を含めば、通常の起動・`-b`・`--check` のどれでも止める。文言は v16 の旧名の検査と同じ形で、「c3c vN で Copilot CLI の opt-in を廃止しました。`.c3c/copilot-version.txt` を消してから起動してください」と、`COPILOT_PAT` も不要になったことを書く。`--check` では `[ERROR]` で出し、ほかの検査は続けたうえで非 0 で終わる（既存の `--check` の止まる検査と同じ扱い）。
- 置き場所は、ほかの検査を続けられる `guard_build_input_defaults()` の近くにする（計画者の判断）。v16 の旧名の検査は `select_project_conf_dir()` の中にあり、`--check` でそこが失敗するとそのプロジェクトの残りの診断を飛ばすので、そこには置かない。
- 止めないのは「中身が空白だけの通常のファイル（symlink でない）」だけにし、それ以外（symlink、ディレクトリ、リンク先の無い symlink、読めないファイルなど）は何であっても止める（計画者の判断）。今の上書きできるビルド入力は `resolve_asset_source()` が `-f` で見るので、ディレクトリや壊れた symlink は黙って同梱の既定値に落ちる。それに合わせると「黙って無視しない」に反するため。
- 試験: 版が書いてあると止まる（起動と `--check`。`--check` ではほかの診断も出る）、空白だけの通常のファイルなら止まらない、ファイルが無ければ止まらない、ディレクトリ・symlink なら止まる、を `tests/test_c3c_config.py` などの既存の試験の流儀で足す。

## `HOME_MOUNT` の秘密の検査の理由

`HOME_MOUNT`・`HOME_MOUNT_RO` が秘密と認証の置き場（`SECRETS_DIR`、`CODEX_DIR`、`~/.claude`、基点の `.claude.json`）と重なる値を拒む検査は残す（持ち主の決定）。今の理由（`c3c` のコメントと ERROR の文、README の `HOME_MOUNT` の節、不変条件）は「Copilot の起動口の sandbox はパスで隠しているので、別の位置に見せると読める」だけなので、次の 2 つに書き直す。

- 作り直していない古いイメージには Copilot の起動口が残り、その sandbox は今もパスで隠している（古いイメージは止めないため）。
- 秘密を 2 つ目のパスに見せると、パスで隠す仕組みを将来足しても効かなくなる。秘密の置き場は決まったマウント先だけに置く（多層の防御）。

README の「ほかの CLI から見えるか」の Copilot の行は消し、Codex の行は残す。

## このリポジトリ自身の手順（保守者）

- 保守者の手元の `.c3c/copilot-version.txt`（gitignore 済み、`latest`）は、新しい版で起動する前に消す。消さないと、上の検査で起動が止まる（それで検査が効くことを実機で確かめてよい）。
- ホストの Copilot CLI のアンインストール、Copilot のホストの設定と一時の作業場所の片付け、`COPILOT_PAT` の失効は、製品の変更の外で保守者が行う（計画では最後の手順として書くが、公開の計画には手元のパスを書かない）。

## 残すもの（念のため）

- Codex の同梱 bubblewrap（#145）と、その検査。
- `HOME_MOUNT`・`HOME_MOUNT_RO` と、その検査（秘密の置き場との重なりの検査を含む。文言だけ直す）。
- 過去の計画と設計の文書。

## 実装者に任せること

- 削除の順番と commit の分け方。
- README の新しい短い節の置き場所と文面（廃止の事実、止まる条件、消し方、`COPILOT_PAT`）。
- `--check` の空のファイルの `[INFO]` を出すか。

## 検証

- `./lint.sh`（警告ゼロ）、`./test-build.sh` の該当するモード（少なくとも `--launcher-only` 相当の Python の試験と `--build-only`）、README「変更後の確認」節にある残りの検証。
- `git grep -niE 'copilot'` で、残してよいもの（GitHub MCP の URL、許可リストの `api.githubcopilot.com`、過去の計画と設計、廃止を伝える README の節と検査）だけが出ること。
- 実機: 版を書いた `copilot-version.txt` のあるプロジェクトで、起動と `--check` が止まる。消すと起動する。`-b` で作り直したイメージに `copilot` が無い。
- タグ: MAJOR（v21.0.0 の見込み）。タグの前に、`--check` が残った `copilot-version.txt` を検出することを実機で確かめる（root `AGENTS.md`）。
