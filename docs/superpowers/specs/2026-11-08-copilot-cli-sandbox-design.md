# コンテナの中で GitHub Copilot CLI を sandbox 付きで動かす（設計）

## 意図

保守者は、Codex CLI と並べて GitHub Copilot CLI をレビューに使っている。いまは Copilot CLI の sandbox がホストでしか動かないため、コンテナの中のセッション（活発なのは findsummits）からは Copilot を走らせられない。c3c のコンテナの中でも、Copilot CLI を **sandbox を有効にしたまま** 動かせるようにする。

この文書は c3c（製品）の部分だけを扱う。コンテナのセッションから保守者の並走の仕組みを起動する部分（台帳・予算の共有、運用規則の変更）は、c3c の外の別の仕事で、この設計が実装された後に別に設計する。

## 目標

- `.c3c/` の設定で opt-in したプロジェクトの Claude のコンテナで、Bash ツールなどから名前で呼んだ `copilot`（主に非対話の `copilot -p`）の command sandboxing が起動し、シェルのコマンドがその中で動く。sandbox の設定は `sandbox.enabled: true`、`allowBypass: false`、外への通信なし（`allowOutbound: false`、`allowLocalNetwork: false`）、`auth.git`・`auth.gh` は false。
- その sandbox の中のコマンドからは、次が見えない、または届かない。
  - 外への通信（ネットワークは `lo` だけ）
  - Copilot の認証のトークン（環境変数でもファイルでも）
  - `SECRETS_DIR` のマウント先、gh の設定、Copilot の設定ディレクトリ（`COPILOT_HOME`）
- opt-in していないプロジェクトのイメージと起動は、今とまったく同じ（パッケージ・中継・マウント・ファイアウォールの許可リストのどれも増えない）。

## 目標にしないこと

- Copilot の sandbox を無効にした使い方の支援。
- 外への通信を許す sandbox の設定。MXC は、その設定では slirp4netns と `/dev/net/tun` を使い、sandbox を外側のユーザー名前空間に入れる（`ProxyOnly` と `FirewallEnforced` のモード）ので、下の実測が当てはまらない。対応しないことを文書に書き、起動口で止める。
- `--agent codex` のコンテナや Codex の sandbox の中からの起動。
- コンテナの中での Copilot の対話的な使い方の作り込み（動けばよい）。
- 保守者の並走の仕組み（上記）。

## 失敗とみなすこと（動いても失敗）

- opt-in していないプロジェクトの境界が変わる。
- コンテナの既存の保護（capability の剥奪、`/proc` のマスクと読み取り専用、ファイアウォール、`:ro` のマウント）を弱めて動かす。特に Podman の `unmask=/proc/*` は使わない（#140 の判断を維持する）。`/dev/net/tun` もコンテナに通さない（下の実測で不要と分かった）。
- トークンが sandbox の中から読める。

## 試作で分かったこと（2026-11-08、使い捨てのコンテナ）

findsummits のイメージ（`debian:testing`）に bubblewrap 0.13.1 を apt で足し、c3c と同じ実行時の条件（`--userns=keep-id`、`NET_ADMIN`/`NET_RAW`、製品の ENTRYPOINT による capability 剥奪、`init-firewall.sh`、IPv6 無効）で試した。Copilot CLI は 1.0.103（linux-x64）、モデルは gemini-4-argon。canary は 3 回で、合計約 6.2 クレジット。

1. Copilot の sandbox（MXC の bubblewrap backend）は、常に `--proc /proc` を bwrap に渡す（MXC の `src/mxc-sdk/src/backends/bubblewrap/common/bwrap_command.rs`）。c3c のコンテナでは Podman の `/proc` のマスクのためにこれが `Can't mount proc on /proc: Operation not permitted` で失敗する（#140 の Codex と同じ原因）。MXC には、Codex のような「マウントできなければ外側の `/proc` を引き継ぐ」予備の道が無い。
2. MXC は bwrap を `PATH` の先頭から探し、引数は argv で渡す（MXC の `docs/backends/bwrap/bubblewrap-backend.md` の「Host tool lookup」）。`PATH` の先頭に、`--proc /proc` だけを `--ro-bind /proc /proc` に替えて本物の `/usr/bin/bwrap` を exec する中継を置くと、Copilot の sandbox が起動した。
3. そのとき sandbox の中では、ユーザー名前空間とネットワーク名前空間が外側と別、ネットワークは `lo` だけ（名前も引けない）、`/tmp` は専用の空のもの、設定で隠した gh の設定と `/run/secrets` は見えなかった。
4. 外への通信を一切許さない設定は MXC の `Isolated` モードになり、slirp4netns を使わない（`ResolvedNetworkMode::from_request`）。3 回目の canary で、`/dev/net/tun` を通さず slirp4netns も入れないコンテナで、2 回目と同じ結果になった。Copilot のヘルプ（1.0.103）は「どの sandbox も slirp4netns と `/dev/net/tun` が要る」と書くが、この設定では要らなかった。
5. 外側の `/proc` を引き継いでも、外側のプロセスの `environ`・`root`・`cwd` は Permission denied（sandbox が別のユーザー名前空間のため。目印を外側と sandbox の中で分けて確かめた）。見えるのはプロセスの一覧とコマンドラインだけ。sandbox の中のプロセス自身の環境は見える（Copilot の環境を引き継ぐ）。
6. MXC は既定で何も読ませない。読めるのは決まったシステムのディレクトリ（`/bin`・`/sbin`・`/lib*`・`/usr/bin`・`/usr/sbin`・`/usr/lib*`・`/usr/libexec`・`/usr/share`・`/etc`。`BASELINE_RO_BIND_PATHS`）と、作業ディレクトリ（`addCurrentWorkingDirectory`）と、設定で許したパスだけ。`/home/node`（`~/.claude`、`~/.codex` を含む）、`/shared`、`/data` は、作業ディレクトリでなければ見えない。
7. Copilot の通信先として、`api.individual.githubcopilot.com` と `telemetry.individual.githubcopilot.com` を許可リストに足した（個人のプラン）。
8. トークンを環境変数にせず、ファイル（試作では使い捨てのコンテナの gh の設定ファイル）から読ませて認証できた。Copilot のヘルプによると、sandbox は「決まった blocklist を除いて」シェルの環境を引き継ぐので、トークンを Copilot の環境変数で渡すと sandbox の中から見える恐れがある（未確認）。トークンは Copilot Requests の権限だけの fine-grained PAT。
9. bubblewrap の最小の版は 0.5.0（MXC の `MIN_BWRAP_VERSION`。`--clearenv` のため）。

## 決まったこと（保守者の決定）

- 実装の対象は c3c の製品で、プロジェクトごとの opt-in にする。
- 必要な部品は次の 3 つで、opt-in したプロジェクトにだけ入れる。
  - イメージに bubblewrap（Debian の apt）を入れる
  - root が持つ bwrap の中継を置き、Copilot にだけ `PATH` の先頭で見せる
  - Copilot の宛先をファイアウォールの許可リストに足す
- Copilot CLI 本体は、Codex と同じく版を固定して入れる。
- 中継は c3c の独自の部品なので、上流の MXC に予備の道（`/proc` をマウントできないときに外側の `/proc` を引き継ぐ）を要望し、入ったら中継を外す。
- トークンは、Copilot Requests の権限だけの専用の fine-grained PAT にし、`SECRETS_DIR` の直下（export されない）に置く。メイン PAT は使わない。

## 判断（設計者の判断。保守者が読んで直せる）

- 守る相手は「sandbox の中でモデルが打つコマンド」とする。コンテナの中の外側のセッション（Claude）は、もともとコンテナの中で何でもできるので、この設計の守りの対象にしない。
- そのため、`COPILOT_HOME` は作業ディレクトリの外に置く（sandbox の中から見えず書けない）。起動口は、Copilot を起動する前に、実効の sandbox の設定（上の「目標」の値）を検査し、違っていれば起動しない（fail-closed）。外への通信を許す設定もここで止める。
- 作業ディレクトリは sandbox から読める（書けるかは MXC の既定に従う）。起動口は作業ディレクトリを変えないので、利用者は Copilot に見せてよいディレクトリで起動する。このことを README に書く。
- `/dev/net/tun` と slirp4netns は入れない（通信なしの設定では要らないと実測した）。Copilot のヘルプとの食い違いは README に書き、Copilot の版を上げるときの受け入れの試験で確かめ直す。

## 制約

- root の `AGENTS.md` と `docs/development-invariants.md` の不変条件に従う（fail-closed、`source` しない、トークンを export しない、アセットのハッシュ照合、マウントの `:ro` 保護、入力検証）。中継と起動口は、Codex の固定リンク（#145）と同じく root 所有で、group/other から書けないことをビルドで検査する。
- 中継が書き換えるのは、連続した 2 つの引数がちょうど `--proc` と `/proc` の組のときだけにする。ほかの引数は一切変えない。組が見つからないときは、そのまま本物の bwrap に渡す（今の失敗の形に戻るだけで、守りは弱まらない）。中継は Copilot 以外（Codex や利用者のコマンド）の bwrap に効かないようにする。
- 挙動が変わるので、README.md の該当節（利用側プロジェクトの設定、GitHub トークンの配線、セキュリティモデル、何ができて何ができないか、変更後の確認）を同じ commit で更新する。opt-in の設定は利用者から見えるインターフェースが増えるので、SemVer のタグの提案の対象になる。

## 作る人に任せること

- opt-in の設定の形（たとえば `.c3c/copilot-version.txt` を足し、既定は空＝無効、版を書けば有効）。Codex の `codex-version.txt` に合わせるのが自然だが、既定が逆（Codex は既定で有効、Copilot は既定で無効）になる点を文書で明示する。
- Copilot CLI の入れ方と照合の方法（npm の `@github/copilot` と、プラットフォーム別の `@github/copilot-linux-x64`）。
- 中継と起動口の置き場所と名前、`PATH` の固定の仕方（Codex の `codex-launcher.sh` のような、npm の symlink を起動口に置き換える形など）。`--check` で何を診断するか。
- トークンの渡し方の具体（Copilot がトークンを読む経路のどれを使うか。PAT のファイル名、`COPILOT_HOME` の置き場所と永続化）。条件は、sandbox の中から環境変数でもファイルでも読めないことを、受け入れの試験で確かめること。
- 許可リストの足し方（opt-in のときだけ足す。名前は個人のプランの 2 つ。ほかのプランは対象外と文書に書くか、設定で足せるようにする）。
- 試験の形（`test-build.sh` のモード、`tests/` の診断スクリプト。少なくとも「opt-in しないイメージが変わらない」「sandbox の中から外へ出られない」「トークンと隠したパスが読めない」「中継が `--proc /proc` 以外を変えない」「起動口が弱めた sandbox の設定で止まる」を確かめる。モデルを呼ぶ試験は手動の受け入れに回し、CI では呼ばない）。
- 上流の MXC への要望の書き方と出す時期。
