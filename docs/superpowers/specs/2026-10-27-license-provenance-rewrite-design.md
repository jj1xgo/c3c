# 上流と Anthropic の devcontainer から引き継いだコードを書き直す 設計

**状態:** 設計の合意済み（持ち主 2026-10-27）。持ち主の spec レビュー待ち。
**区分:** 境界（`init-firewall.sh` はエグレス制限の中心で、`docs/development-invariants.md` の不変条件に触れる。`LICENSE` の変更は対外的で取り消しにくい）。
**関連:** [#225](https://github.com/jj1xgo/c3c/issues/225)。fork の関係を切る試験の結果は #225 のコメントにある（切るかどうかは本設計の範囲外）。

## 目的

c3c は全体を GPL-3.0 として配布している。その中に、帰属の論点を持つコードが 2 種類ある。

1. フォーク元 sethjensen1/claude-container（MIT）の作者が書いた行。2026-10-27 の main（03ee1c6）で `git blame -w -M -C` の作者がフォーク元の作者になる行は、`c3c` 21 行、`Dockerfile.claude` 14 行、`compose.yml` 13 行、`.gitignore` 1 行の計 49 行（空行を含む）。MIT は表示を残せば使えるが、残す限り `LICENSE` に MIT の全文が要る。
2. Anthropic の devcontainer（anthropics/claude-code の `.devcontainer/`）を元にした部分。`init-firewall.sh` は冒頭のコメントで「移植」と明記している（4dcfae5）。`Dockerfile.claude` にも同じ形の行がある。Anthropic の公式ドキュメントは、この devcontainer を動く例として示し、自分のリポジトリへコピーして調整するよう案内している。一方、そのリポジトリの LICENSE は「All rights reserved」で、GPL として第三者へ再配布する許諾は書かれていない。

この 2 種類を c3c 自身の書き方で書き直し、帰属の論点そのものを無くす。そのうえで `LICENSE` と README の表示を整理する。法的な判断は行わない。書き直しで論点を無くす方針の記録である。

## 成功条件

- フォーク元の作者の行が、`git blame -w -M -C` で 0 行になる。ただし、下の「字面が同じでよいもの」に当たる行は、作者の帰属が残ってもよい。その場合は、行と理由を PR 本文に列挙する。
- `init-firewall.sh` は、関数の分け方・処理のまとまり・コメント・自己検証の組み立てを、c3c の不変条件と README の仕様から組み直したものになる。Anthropic 版と同じ形の流れ（下の「`init-firewall.sh`」）が、そのままの並びで残らない。
- 挙動が変わらない。基準は下の「挙動が変わらないことの確かめ方」。
- `LICENSE` に MIT の全文が無く、本文は GPL-3.0 だけ。git の履歴の初期の版に、他者のコードが含まれていたことを短い注記で示す（下の「表示の整理」）。
- `init-firewall.sh` と README から「移植」の記述が無くなる。

## 非目標

- 挙動・CLI 引数・`.c3c/` の設定形式・既定値・イメージの label・コンテナ内のパスを変えること。
- git の履歴を書き換えること。過去の commit・タグ・Release は変えない。
- GitHub の fork の関係を切ること（持ち主が別に決める）。
- ファイアウォールの改良（`iptables-restore` による一括適用、ルールの並べ替え、検証項目の追加など）。気づいた改良は Issue に分ける。
- c3c の作者が書いた部分の書き直し（ポート制限、世代タグ、`--refresh-domains`、IPv6 helper の連携、許可ドメインの検証など）。

## アンチゴール（技術的に動いても失敗とみなすもの）

- ルールの並びや対象が、書き直す前と変わっていた。ファイアウォールでは順番が意味を持つので、「たぶん同じ」は合格にならない。
- 書き直しのときに、上流か Anthropic の元ファイルを開いて、それを見ながら書いた。
- 既存のテストが関数名で抽出している関数（`tests/test-domain-rule-lifecycle.sh` などが `sed -n "/^name()/,/^}/p"` で取り出す）の名前を変えて、テストを黙って直した。名前を変えるなら、テストの抽出も同じ commit で直し、変えた理由を書く。
- `LICENSE` の GPL-3.0 の本文を変えた。

## 字面が同じでよいもの

名前や値そのものが機能や互換性を決めていて、別の書き方にすると挙動か互換性が壊れるものは、同じ字面のまま残す（この線引きは計画者の判断）。

- compose のキーと値（`stdin_open: true`、`tty: true`、`userns_mode: keep-id`、`working_dir` など）と、サービス名 `claude-auth-workspace`（イメージ名と既存の state が使う）。
- 環境変数・ARG・パスの名前（`ENV DEVCONTAINER=true`、`ARG CLAUDE_CODE_VERSION`、`/workspace`、`/home/node/.claude`、`/usr/local/bin/init-firewall.sh`、`/etc/sudoers.d/` の下のファイル名）。
- Dockerfile の命令そのもの（`WORKDIR /workspace`、`USER node`）。
- iptables の個々のルールの引数（`-A OUTPUT -o lo -j ACCEPT` など）。ルールの内容はファイアウォールの仕様そのものなので、行の字面が一致しても書き直しの対象にしない。書き直しの対象は、それらをどう組み立てるか（関数の分け方、まとめ方、コメント、検証の組み立て）。
- 空行と `.gitignore` の `tmp`。

書き方を選べる部分（引数解析の組み立て、`mkdir` と `chown` の書き方、sudoers の書き込み方、コメント、YAML のキーの並びとコメント）は書き直す。

## 対象ごとの方針

### `c3c`

フォーク元の作者の行は、`BUILD=0` と引数解析の `while`/`case` の骨組み（`-b|--build`、`-h|--help`、`*)` の `POSITIONAL_ARGS+=("$1")`、`set -- ${POSITIONAL_ARGS[@]+"${POSITIONAL_ARGS[@]}"}`）など。今の引数解析の仕様（README の使い方、`usage()`、`set_agent_option()` の規則、`--` の扱い、未知オプションは exit 2）を変えずに、組み立てを書き直す。

### `Dockerfile.claude`

フォーク元の作者の行と Anthropic の devcontainer と同じ形の行は、`ARG CLAUDE_CODE_VERSION=latest`、`ENV DEVCONTAINER=true`、`/workspace` と `/home/node/.claude` の作成と所有者の設定、sudoers の書き込みと mode 0440、`WORKDIR`、`USER node`、空行。名前と命令は残し、書き方を選べる部分（作成と所有者の設定、sudoers の書き込み方、周りのコメント）を書き直す。最終イメージのディレクトリと sudoers ファイルの所有者・mode・中身が変わらないこと。

### `compose.yml`

フォーク元の作者の行は、サービス定義の骨組み（サービス名、`build:`、`stdin_open`、`tty`、`userns_mode`、コメントアウトされた `profiles`、`volumes` の 3 行、`working_dir`）。キーと値は「字面が同じでよいもの」に当たる。コメントアウトされた `#profiles:` の 2 行は、使っていないなら消す。キーの並びとコメントは書き直してよい。`podman compose config` の出力（`lint.sh` が検証する）が変わらないこと。

### `.gitignore`

`tmp` の 1 行は「字面が同じでよいもの」に当たる。変えない。

### `init-firewall.sh`

Anthropic 版と同じ形をしているのは、主に次の 2 か所。

- `full_init()` の流れ: 既存ルールの消去 → loopback と確立済み接続 → DNS → GitHub の範囲 → 許可ドメイン → ホストネットワーク → 既定ポリシーの DROP → 許可リストのチェーンへの jump と REJECT → IPv6 の遮断 → 自己検証。
- `verify_ipv4()` の組み立て（禁止先へ届かないこと、許可先へ届くことを順に確かめる）。
- 冒頭のコメント（「移植」と、Anthropic 版との差分の列挙）。

これらを、c3c の仕様から組み直す。仕様の出どころは、`docs/development-invariants.md` の「`init-firewall.sh`」の項、README の「アーキテクチャ」節の `init-firewall.sh` の説明、`docs/firewall-refresh.md`、今のファイルのうち c3c の作者が書いた部分のコメント。

- ルールを入れる順番は変えない。これは仕様（DNS を許可ドメインの解決より前に入れる、既定ポリシーを DROP にするのは許可ルールの後、など）なので、組み直しても並びは同じになる。
- 書き直しの合格線（計画者の判断）: ルールを変える呼び出しの列（下の「挙動が変わらないことの確かめ方」の 1）が同じであれば、次の 3 点は変えてよい。いずれも行うことを求める。
  - 関数への分け方と名前（c3c の作者が書いた関数は除く）
  - ルールを変えない処理の時機（GitHub meta の読み込みと検査、ホスト IP の検出、IPv6 helper の `prepare` を呼ぶ位置、`disable_ipv6_fallback` の位置など。ただし、DNS の許可より前にネットワークを使わない、fail-closed の停止条件を変えない、の 2 点は守る）
  - コメント
- `verify_ipv4()` は、確かめる項目の集合（example.com に届かない、api.github.com:443 に届く、api.anthropic.com に届く、api.github.com:80 に届かない）と、それぞれの上限時間と失敗時の停止を変えない。項目を確かめる順番と、組み立て（関数の分け方、共通化）は変えてよい。
- 冒頭のコメントは、Anthropic 版との差分としてではなく、c3c のファイアウォールが何をするかの説明として書き直す。
- 自己検証の項目と、失敗時に起動を止める挙動（fail-closed）、メッセージの意味は変えない。メッセージの文面は変えてよいが、テストや README が照合している文字列（`ERROR:` などの接頭辞、README が引いている文）は変えない。
- c3c の作者が書いた関数（`resolve_allowed_ports`、`add_cidr`、`add_cidr_tagged`、`add_or_touch_domain_ip`、`build_domain_list`、`refresh_domains`、`prune_stale_domain_rules`、`do_refresh` など）は残す。名前も変えない（テストが名前で抽出している）。

## 書き直しの進め方

- 実装する人は、上流（sethjensen1/claude-container）と Anthropic の devcontainer（anthropics/claude-code の `.devcontainer/`）のファイルを開かない。`git show` で上流の commit を表示することも含む。
- 仕様は、上の「仕様の出どころ」と今の c3c のテストから読む。今の `init-firewall.sh` は読んでよい（書き直す対象なので）が、`full_init()` と `verify_ipv4()` は、構造をなぞらず、仕様から関数の分け方を決めてから書く。
- **実装の前の一致行の一覧**: 計画者が、元ファイルと今の c3c のファイルを機械的に比べ、一致する行を「c3c のファイル名と行番号」だけの一覧にして計画に載せる（元ファイルの本文は載せない）。実装者はこの一覧で、どの行を書き直すかを知る。一覧の行のうち「字面が同じでよいもの」に当たるものは、一覧の中でそう印を付ける。入力を読む 1 行（`/etc/resolv.conf` や `ip route` の解析など）で一覧に載ったものは、挙動が同じ別の書き方にし、同じ挙動であることを固定入力のテストで確かめる。
  - 比べる元ファイル: Anthropic の devcontainer の `init-firewall.sh` と `Dockerfile` は、今の main と、c3c が移植した 2026-07-02（4dcfae5）の時点の版の両方。上流は最後の commit（e4a9626）の版と、それより前の各 commit の版。
  - 一致の定義: 行ごとに、`#` 以降のコメントと前後の空白を除き、空行を除いたうえでの完全一致。
  - `Dockerfile.claude` の Anthropic と同じ形の行は git blame では出ないので、この比較で測る。
- **実装の後の比較**: 書き直しが終わったら、計画者か独立レビューの側が同じ比較をもう一度行い、結果を PR 本文に書く（元ファイルはリポジトリに入れない）。一致する行は「字面が同じでよいもの」に当たるものだけになっていること。

## 挙動が変わらないことの確かめ方

1. **ルールの組み立ての一致（固定入力）**: `init-firewall.sh` の init モードを、`iptables`・`ip6tables`・`dig`・`curl`・`ip` などを差し替えた環境で走らせ、呼ばれたコマンドの列を記録するテストを作る。書き直す前の版で記録した列を期待値として commit し、書き直した後の版が同じ列を出すことを確かめる。期待値は書き直す前に作り、書き直しと別の commit にする。このテストは、書き直しの後も回帰テストとして残す。
   - 照合する範囲（計画者の判断）: ルールを変える呼び出しだけ。`iptables`・`ip6tables` の変更系（`-F`・`-X`・`-N`・`-A`・`-D`・`-I`・`-P`、`-t` を含む）の引数と順番、`ipv6-firewall.py` の `prepare`・`verify` の引数と、変更系の呼び出しとの前後関係。読むだけの呼び出し（`dig`・`curl`・`ip route`・`jq`・`ip6tables -L` など）の順番と引数、標準出力と標準エラーの文面は照合しない。
   - `verify_ipv4()` の項目は、別に確かめる: 差し替えた `curl` と接続の確認が、4 項目のそれぞれで「届く／届かない」を返したときに、成功と停止が今と同じになること（どれか 1 つが期待と違えば exit 1）。
   - 固定入力は、IPv6 無効（既定）と `--ipv6` の 2 通り、リゾルバあり・なしの両方を含める。
2. **実コンテナでの一致**: 書き直す前と後のイメージでそれぞれコンテナを起動し、`podman exec --user root <container> iptables-save` と `ip6tables-save` の出力を比べる。DNS で解決した IP と世代タグ（`gen=<epoch>`）は起動ごとに変わるので、それらを伏せたうえで、ルールの並びと中身が一致すること。
3. **既存のテスト**: `./lint.sh`、`./test-build.sh --launcher-only`、`./test-build.sh --validator-only`、`./test-build.sh --build-only`、`./test-build.sh --config-ro-only`、`bash tests/test-runtime.sh`（IPv4）、`tests/` の firewall 系のテスト。`--ipv6` の経路も、固定入力のテストで 1 回は通す。実 IPv6 の確認ができなければ `not run` と理由を書く。
4. **イメージの中身**: `/workspace`・`/home/node/.claude`・sudoers のファイルの所有者・mode・中身が、書き直す前と同じ。
5. **起動**: `-b` で再ビルドしたイメージで、Claude と Codex の両方が起動し、許可先へ届き禁止先へ届かない。

2・4・5 はホストの podman が要る。実装はホストのセッションで行う前提にする（このリポジトリのホストには podman 5.8.6 がある）。書き直す前のイメージは、書き直しの commit より前に、別のタグを付けて残しておく。

## 表示の整理

- `LICENSE`: 「Upstream Attribution」の節と MIT の全文を外し、GPL-3.0 の本文だけにする。冒頭の 1 文の後に、次の趣旨の短い注記を置く: 「このリポジトリの git の履歴の初期の版には、sethjensen1/claude-container（MIT）のコードと、Anthropic の devcontainer の例を元にしたコードが含まれる。現在の版では書き直されている。」文面と言語は実装時に決める（`LICENSE` は英語の法文の例外に当たる。README「表記」節）。
- README:
  - 「ライセンス」節: 上の注記と同じ事実を日本語で書く。
  - `init-firewall.sh` の説明（「Anthropic 公式 devcontainer の同名スクリプトの移植」）: c3c のファイアウォールとしての説明に直す。
  - 冒頭の「…をフォークした」と、`AGENTS.md` の同じ表現: 事実（フォークして始めた）は残してよい。fork の関係を切るかは別に決めるので、この PR では変えなくてよい。
- `init-firewall.sh` の冒頭のコメント: 上の方針で書き直す。

## 範囲外

- 過去の Issue・PR・計画・spec の中の記述（「移植」などを含む）。
- vault と ops の記述。
- README の参考リンク（フォーク元の作者のブログ）。

## 実装者に任せる点

- 書き直した後の関数の分け方と名前（c3c の作者が書いた関数は除く）。
- 固定入力のテストの作り方（差し替えの方法、記録の形式、置き場所）。`/etc/c3c/` の下の固定パスを、テスト用にどう差し替えるか。
- `Dockerfile.claude` の作成と所有者の設定、sudoers の書き込みの具体的な書き方。
- `LICENSE` の注記の文面。
- commit の分け方（ただし、固定入力のテストの期待値は、書き直しより前の commit にする）。

## 計画者の判断（持ち主が確かめるもの）

- 「字面が同じでよいもの」の線引き。
- ルールを入れる順番は変えない（仕様とみなす）。
- `init-firewall.sh` の合格線: 関数の分け方・ルールを変えない処理の時機・コメントを変え、ルールを変える呼び出しの列は同じにする。`verify_ipv4()` は項目の集合と停止を変えず、順番と組み立ては変えてよい。
- 固定入力のテストで照合するのはルールを変える呼び出しだけ。
- 実装の前に、計画者が一致行の一覧（行番号だけ）を計画に載せる。
- 固定入力のテストを回帰テストとして残す。
- `.gitignore` の 1 行は変えない。compose のコメントアウトされた `profiles` は、使っていなければ消す。
- README 冒頭と `AGENTS.md` の「フォークした」は、この PR では変えない。
