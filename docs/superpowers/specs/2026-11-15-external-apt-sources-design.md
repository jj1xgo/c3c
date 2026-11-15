# 外部の APT 取得元を `.c3c/` で足す仕組み（設計）

起点: [#273](https://github.com/jj1xgo/c3c/issues/273)（findsummits からの要望。コンテナで Chrome・Brave・Firefox の安定版をヘッドレスで動かしたい）。

## 意図と理由

利用側のプロジェクトが、Debian の外の APT 取得元からパッケージを入れられるようにする。今の `.c3c/packages.txt` は、イメージに設定済みの取得元（Debian と、Dockerfile 固定の GitHub CLI）にあるパッケージしか入れられない。findsummits は、ブラウザで動くビューアの画面テストを実物のブラウザ（Google Chrome・Brave・Mozilla Firefox の安定版の最新）で回すと決めた。しかし 3 つとも Debian の外の取得元にしか無いため、コンテナの中でテストを回せない。

持ち主の判断で、3 つのブラウザに絞った固定の一覧ではなく、**任意の外部 APT 取得元をプロジェクトが足せる汎用の仕組み**にする。

## 目標

- プロジェクトが `.c3c/apt-sources.txt` に取得元を宣言でき、`-b` のビルドでその取得元がイメージに足される。
- 取得元ごとに、鍵束の**主鍵の指紋の集合**をプロジェクトが書き、ビルド時に取った鍵束の主鍵の指紋の集合がそれと完全に一致しなければビルドを止める（fail-closed）。
- 足した取得元のパッケージは、今までどおり `.c3c/packages.txt` に名前を書いて入れる（`packages.txt` の書式と検査は変えない）。
- 確かめ方: findsummits の `docs/decisions/research/browser-automation-probe.md` の「やり直すとき」の 3 つのコマンドが、`-b` で作ったコンテナの中で rc 0 になる（9 つの能力がすべて通る）。

## 目標にしないこと

- ブラウザのための実行時の変更（`/dev/shm` の大きさ、seccomp、capability）。2026-11-15 の試しで要らないと分かった（下の「試しの結果」）。
- パッケージの版の固定（`pkg=version`）。`packages.txt` と同じく、`-b` の時点の最新が入る。
- APT の優先度（`/etc/apt/preferences.d`）の設定。Mozilla は自分の取得元の `firefox` を優先させる pin を推奨しているが、既定の `debian:stable` と findsummits の `debian:testing` には Debian 側の `firefox` パッケージが無いので要らない。`debian:sid` など Debian 側にも同名のパッケージがあるベースでどちらが入るかは、この設計では扱わない（README に注記する）。
- ホストの `/etc/apt` から取り込むこと（検討して採らなかった。下の「作り方の候補」）。
- 実行時に外へ通信すること。ビルドはファイアウォールの外で行われるので、取得元のドメインを `allowed-domains.txt` に足す必要は無い。

## 失敗とみなすこと（動いても）

- 指紋の照合を通らない鍵、または照合できなかった鍵（取得の失敗、鍵の形式が読めない）で、ビルドが成功する。
- `trusted=yes`・`allow-insecure` など、署名の検査を弱める指定をプロジェクトが書ける。
- `http://` の取得元が通る（今のイメージは apt の取得元が `http://` で残らないことを 2 か所で確かめている。この検査を外したり、例外を作ったりする）。
- 宣言していない主鍵が鍵束に混じっていても、ビルドが成功する。
- 境界のファイル（`init-firewall.sh`・`entrypoint.sh` など）が、upgrade の層（#248）で外のパッケージのインストールスクリプトに正直に（隠す意図なく）変えられたまま、ビルドが成功する（下の「境界のファイルの照合」）。upgrade の層より前の層での書き換えは、ここに含めない（持ち主の判断、2026-11-15。下の「境界のファイルの照合」の「照合の範囲」）。
- `apt-sources.txt` を置かないプロジェクトのイメージや起動が、今と変わる（警告が増えることを含む）。

## 制約

- 公開の不変条件（`docs/development-invariants.md`）に従う。とくに、入力検証を `apt-get` の実行より前に置くこと、`validate-build-input.sh` をビルド時・`--check`・`test-build.sh` の 3 者で共有すること、境界アセットの解決（`resolve_asset_source()`・`ASSET_HASH_TARGETS`・`stage_build_context()`）を 1 か所に保つこと。新しいアセット名を足すときは、既存アセット名の全参照を `grep -rn` で数え直す（不変条件の文面どおり）。
- 脅威の位置づけ: `.c3c/` を書ける者は、今でも `requirements.txt` 経由でビルド時に root で任意のコードを動かせる（README の「残余」節）。外部の取得元を足すことで、新しい種類の穴は開かない。ただし、README の「apt 側は設定済みリポジトリ内のパッケージに限られる」という文は偽になるので書き直す。足した取得元は、`-b` のたびに走る upgrade の層（#248）からも引かれる。
- 境界のファイルの多くは、`packages.txt` の層より後で `COPY` されている。ただし `/etc/claude-code/managed-settings.json`（#243）は外部の取得元の層より前に作られ、Codex の起動口（`/usr/local/bin/codex`）・`/usr/local/libexec/c3c/codex-bwrap`・`/etc/codex/requirements.toml` は Copilot の bubblewrap の導入の層より前に置かれる（PR #274 の PR 後レビューで分かった）。外部の取得元とその導入は `packages.txt` の層より前に置き、この順序を崩さない。ただし、`-b` のたびに走る upgrade の層（#248）は境界のファイルの `COPY` より後にあるので、外の取得元のパッケージの更新では、そのインストールスクリプトが境界のファイルの後に root で走る。
- 取得元を足すことは、その提供元にビルド時の root を（初回の導入と、`-b` のたびの upgrade で）渡すことと同じである。悪意のあるパッケージは、境界のファイルに触れずに `setpriv`・`sudo` などを差し替えられるので、c3c の検査では防ぎきれない。持ち主はこれを `requirements.txt` と同じ種類の残余として受け入れた（2026-11-15）。README の「残余」節に書く。

## 作り方の候補

| 案 | 中身 | 得失 |
|---|---|---|
| **A（採用）** | `.c3c/apt-sources.txt` に 1 行で取得元と鍵の URL・主鍵の指紋を宣言する。ビルド時に鍵を取り、指紋で照合する。sources は c3c が組み立てる | 書く欄が狭く、検査が `packages.txt` の流儀の延長で済む。どの機械でも同じイメージになる。主鍵が変わらない限り鍵の更新に追従する。1 行に収まらない指定（pin など）は扱えない |
| B | 鍵のファイルそのものをプロジェクトに commit し、決まった欄だけの sources を置く | 鍵の中身が git の差分でレビューに乗る。鍵の更新のたびに各プロジェクトで差し替えが要る |
| C | deb822 の `.sources` ファイルを丸ごと受ける | 最も柔軟だが、開いた書式に対して危ない欄を拒否する検査を書くことになり、入力検証を狭く保つ方針に合わない |
| D | ホストの `/etc/apt/sources.list.d/` と鍵を名前で取り込む | 指紋を書かずに済み、信頼の起点がホストの root 所有のファイルになる。ただし、イメージがホストの状態で変わる（別のホスト・Mac の podman machine・`test-build.sh` では止まる）。「イメージはプロジェクトの設定と c3c だけで決まる」という今の作りの例外になる |

持ち主が A を選んだ（2026-11-15）。決め手は、c3c が公開の製品で、どの機械でも同じイメージになることを優先したこと。

## 決めたこと

### 書式（持ち主と合意）

`.c3c/apt-sources.txt` は 1 行に 1 取得元。行頭 `#` はコメント、空行は無視する。欄は空白で区切る:

```
<名前> <鍵の URL> <主鍵の指紋>[,<主鍵の指紋>...] <URI> <suite> <component> [<component>...]
```

指紋の欄はカンマ区切りで複数書ける（持ち主の判断、2026-11-15。builder check で、鍵束に宣言していない主鍵が混じっても通る穴が見つかったため、合意した書式を広げた）。

例（2026-11-15 に取得した主鍵の指紋）:

```
google-chrome https://dl.google.com/linux/linux_signing_key.pub EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796 https://dl.google.com/linux/chrome/deb/ stable main
mozilla https://packages.mozilla.org/apt/repo-signing-key.gpg 35BAA0B33E9EB396F59CA838C0BA5CE6DC6315A3 https://packages.mozilla.org/apt mozilla main
brave-browser https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg DBF1A116C220B8C7164F98230686B78420038257,47D32A74E9A9E013A4B4926C68D513D36A73CD96,B2A3DCA350E67256740DF904DE4EC67BE4B0DCA0 https://brave-browser-apt-release.s3.brave.com/ stable main
```

### 照合

- 鍵は HTTPS で取る。取得に失敗したらビルドを止める。
- 取った鍵束の**主鍵の指紋の集合**が、宣言した指紋の集合と完全に一致しなければ（足りない、または余分がある）ビルドを止める。提供元が主鍵を足したり替えたりしたら、プロジェクトが指紋を書き直すまでビルドは止まる（意図した fail-closed）。
- 指紋を読む道具: 今のイメージには gpg が無い。`apt-sources.txt` が空でないときだけ、取得元を足す RUN の中で Debian の `gnupg` を入れる（作成者の判断。空のプロジェクトのイメージを変えないため）。入れた `gnupg` を後で消すかは作る人に残す（利用側が `packages.txt` で `gnupg` を求めている場合と食い違わないこと）。
- 鍵の取り直し（作成者の判断）: 取得元を足す RUN は `apt-sources.txt` が変わらなければキャッシュから使われ、鍵は取り直されない。提供元が署名の副鍵を替えると、upgrade の層（`--error-on=any`）で `-b` が止まり続ける。そこで、upgrade の層の中で `apt-get update` の前に、宣言した取得元の鍵をもう一度取り、同じ規則で照合して置き直す。upgrade の層は `-b` のたびに作り直されるので、後ろの層を作り直す費用は増えない。鍵の配信元が止まっているときは `-b` が止まる（取得元自体が止まっているときに今の upgrade の層が止まるのと同じ扱い）。
- sources の行は c3c が `deb [signed-by=<その取得元専用の鍵のファイル>] <URI> <suite> <component...>` の形で組み立てる。プロジェクトの文字列を apt のオプションの位置に入れない。

### 置き場所と層

- `apt-sources.txt` はアセットの区分では optional（`allowed-ports.txt` と同じく、プロジェクトに無ければ空のファイルとして扱い、警告を出さない）。ハッシュとステージングは既存の解決の規則を通す。
- 取得元を足す RUN は、`packages.txt` の検査と導入の RUN の直前に置く。`apt-sources.txt` が空なら何もしない。

### パッケージが自分で足す取得元（作成者の判断）

Google Chrome のパッケージは、インストールのときに自分の取得元（`/etc/apt/sources.list.d/google-chrome.sources`、URI は `https://dl.google.com/linux/chrome-stable/deb/`）と鍵（`/usr/share/keyrings/google-chrome.gpg`）を足す。c3c はこれを消さない。理由: 照合した鍵と同じ発行元が、署名されたパッケージで足したものであり、消すとパッケージ自身の更新の手段と食い違う。2026-11-15 の試しでは、両方があっても `apt-get update` は rc 0 で通った。README には、照合するのは宣言した取得元の初回の取得までで、パッケージが後から足す取得元と鍵は照合の外だと書く。

### 境界のファイルの照合（持ち主の判断、2026-11-15）

upgrade の層の後（今のビルド時アサーションと同じ位置）に、境界のファイル（`Dockerfile.claude` が `COPY` する root 所有のスクリプトと設定）が、ビルドコンテキストの原本と同じ内容かを照合し、違えばビルドを止める層を足す。照合は、外の取得元が無いプロジェクトでも常に行う（作成者の判断。`packages.txt` の Debian のパッケージでも同じ壊れ方は起こりうるため。照合の層が増えるだけで、イメージの中身は変わらない）。正直な壊れ方（インストールスクリプトがたまたま同じパスを上書きした）だけを捕まえるもので、悪意のある差し替えは防げない（`setpriv` のアサーションと同じ位置づけ）。対象のファイルの一覧と、原本との比べ方（ハッシュをビルド時に記録するか、原本を `/tmp` に置いて比べて消すか）は作る人に残す。

実装では、原本とは比べず、upgrade の層の前後の状態（パス・種類・所有者・mode・symlink の先・内容の sha256）を比べた（`check-boundary-files.sh`。`allowed-domains.txt` のように `COPY` の後に `Dockerfile.claude` が書き足すファイルがあり、原本と比べると誤検知になるため）。

照合の範囲（持ち主の判断、2026-11-15。PR #274 の PR 後レビューで分かった）: 照合するのは upgrade の層の前後だけである。`/etc/claude-code/managed-settings.json`（#243）は外部の取得元の層より前に作られ、Codex の起動口（`/usr/local/bin/codex`）・`/usr/local/libexec/c3c/codex-bwrap`・`/etc/codex/requirements.toml` は Copilot の bubblewrap の導入の層より前に置かれるので、upgrade の層より前でパッケージを入れる層（外部の取得元の層が gnupg を入れるとき、`packages.txt` の層、Copilot の bubblewrap の導入）のインストールスクリプトがこれらを書き換えても、照合では気づけない（その層の後の状態が比べる基準になる）。その層の前後にも照合を足す案は採らなかった（コードと試験が増え、#243 の不変条件が早い層の root の `RUN` からは守らないと整理済みのため）。

### 実行時（作成者の判断）

変えない。下の「試しの結果」のとおり、c3c の今の権限の設定と `/dev/shm` の既定（64MB）で、3 つのブラウザが `--no-sandbox` なしのヘッドレスで 9 つの能力をすべて通した。

## 試しの結果（2026-11-15、使い捨て）

findsummits の c3c イメージ（ベース `debian:testing`）に 3 つの取得元を手で足したイメージを作り、compose と同じ権限の設定（`userns keep-id`、`cap_add NET_ADMIN NET_RAW`、IPv6 無効、既定の seccomp、`setpriv --ambient-caps=-all --inh-caps=-all` と tini、ユーザー node）で、ネットワークなしで probe の 3 コマンドを走らせた。

| ブラウザ | 版 | 9 つの能力 | rc |
|---|---|---|---|
| Google Chrome | 157.0.8103.78 | すべて通過 | 0 |
| Brave | 157.1.99.57 | すべて通過 | 0 |
| Firefox | 160.0 | すべて通過 | 0 |

`/dev/shm` は終了時に 0% の使用で、起動したブラウザは残らなかった。Chromium 系は sandbox が使えないと `--no-sandbox` なしでは起動しないので、Chromium 系の sandbox は動いている。Firefox の sandbox の段階は確かめていない。試しはファイアウォールを通していない（ネットワークなしで走らせたため。probe は外へ通信しない）。

## 作る人に残すこと

- `validate-build-input.sh` に足す kind の名前と、各欄の正規表現（名前、HTTPS の URL、40 桁の 16 進、suite・component の文字の範囲）。URI と鍵の URL の `https://` の強制と、空白・制御文字・`[`・`]` の拒否は必須。
- 名前の重複、同じ鍵のファイルの名前の衝突、ファイル名に使う文字の範囲。
- 鍵の形式（ASCII armor とバイナリ）を両方受けること、`signed-by` に置く形（`gpg --dearmor` するか、そのまま置くか）。
- `Architectures` の扱い（Google Chrome は amd64 だけ。arm64 のビルドで apt がどう振る舞うか確かめ、必要なら欄を足すか README に書く）。
- `--check` での内容の診断（`packages.txt` と同じく助言だけ）。
- `test-build.sh` の検査（書式の拒否の場合、指紋の不一致でビルドが止まること、空のときに層が何もしないこと）と、README の「変更後の確認」節への追記。
- README（利用側プロジェクトの設定の節、ファイルの一覧、「残余」節の書き直し）と `docs/development-invariants.md` の更新。
- 利用者から見える設定の形式が増えるので、SemVer の minor の候補（タグは持ち主の承認の後）。
