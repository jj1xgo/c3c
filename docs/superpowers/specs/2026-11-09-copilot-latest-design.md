# Copilot CLI をビルド時の最新版で入れる（設計）

## 意図

`copilot-version.txt` は今、`1.0.103` のような番号しか受けない（`latest` を書くとビルドの前に ERROR）。保守者は、版を上げるたびに番号を調べるのが手間で、また最新を使うのが保守者のポリシーなので、`-b` でビルドしたときにその時点の最新版が入るようにしたい。

番号に限っていたのはわざとで、前回の設計（`docs/superpowers/specs/2026-11-08-copilot-cli-sandbox-design.md`）は「Copilot CLI 本体は、Codex と同じく版を固定して入れる」と決めていた。Copilot の command sandboxing（MXC の bubblewrap、通信なし）が c3c のコンテナで効くことを、1.0.103 でだけ確かめたからである。新しい版で、sandbox の設定の項目名や挙動が変わると、エラーも出ないまま「通信なし」が外れるおそれがある。この設計は、`latest` を受けるかわりに、その危険を拾う仕組みを 2 つ足す。

## 目標

- `copilot-version.txt` に文字どおりの `latest` を書けるようにする。`-b`（とイメージが無いときの明示のビルド）のたびに、npm の dist-tag で解決したその時点の最新版が入る。Codex の `latest`（`CODEX_CACHEBUST`）と同じく、Copilot のレイヤーのキャッシュだけを捨てる。
- 番号での固定（`X.Y.Z`）と空（入れない、opt-in の既定）は今までどおり。c3c が同梱する `copilot-version.txt` は空のまま。
- **ビルドの中の確認（止める）**: 入った版の Copilot が、c3c の sandbox の設定の雛形（`copilot-settings.json`）を、全部の項目について同じ名前・同じ値で読めていることを確かめ、違えばビルドを失敗させる。版が `latest` でも番号でも行う。
- **起動時の知らせ（止めない）**: 入っている版が「c3c が canary で sandbox を確かめた版」と違えば、`copilot` の起動のたびに WARNING を出し、canary を回すよう促す。起動は止めない。

## 目標にしないこと

- 「実際に通信が塞がれるか」をビルドの中や起動のたびに機械で確かめること。下の調査のとおり、Copilot の sandbox は、ログインしてモデルを走らせないと動かせない（canary は 1 回 2 クレジットほど）。
- 利用者ごとの「確かめた版」の記録。`COPILOT_HOME`（`~/.copilot`）はマウントせず、コンテナを作り直すと消えるため。
- 版を上げたときの canary の自動化。保守者が手で回す。
- Copilot の自動更新（`copilot update`）。今までどおり `COPILOT_AUTO_UPDATE=false` で止める。

## 失敗とみなすこと（動いても失敗）

- 新しい版で sandbox の設定の項目が 1 つでも黙って捨てられたのに、ビルドが通る。
- opt-in していない（空の）プロジェクトのイメージ・起動・キャッシュの効き方が変わる。番号で固定したプロジェクトのキャッシュが、`-b` のたびに捨てられる。
- 起動時の WARNING が、確かめた版と同じ版でも出る（警告が常に出ると読まれなくなる）。
- 前回の設計の「失敗とみなすこと」（既存の保護を弱める、トークンが sandbox の中から読める、など）のどれか。

## 調べて分かったこと（2026-11-09、c3c のコンテナ、Copilot CLI 1.0.103）

1. sandbox をモデル無しで単体で動かす道は無い。`copilot sandbox` のサブコマンドは `ca`（証明書の管理）だけ。MXC は Copilot のネイティブのバイナリ（`@github/copilot-linux-x64/copilot`、約 200MB）に組み込まれていて、外から呼べる別のプログラムは無い。
2. `copilot config --list --json` は、ログインも通信も無しで（`env -i HOME=<一時> COPILOT_HOME=<一時> PATH=/usr/local/bin:/usr/bin:/bin node <pkg>/npm-loader.js config --list --json`）、`COPILOT_HOME` の `settings.json` を Copilot がどう読んだかを JSON で返す。c3c の雛形を置くと、全部の項目が同じ値で返った（JSON として等しい。項目の並びは違う）。rc 0。
3. 知らない項目は黙って捨てられる。`{"sandbox":{"enabled":true,"bogusKey":1}}` では、`--list` に `sandbox.enabled=true` だけが出て、`bogusKey` は出なかった。`copilot config sandbox.bogusKey` は `Error: Unknown settings key segment "bogusKey" at "sandbox".` で rc 1。
4. `--list` に出るのは設定した項目だけで、既定値は出ない（3 の例で、ほかの sandbox の項目は出なかった）。
5. ビルドの中で bwrap が動くか（`podman build` の RUN で user namespace が使えるか）は、コンテナの中に podman が無いので調べていない。2 の確認は bwrap を使わないので、この問題に当たらない。

## 決まったこと（保守者の決定、2026-11-09）

- `latest` を受ける。最新を使うのが保守者のポリシーで、番号を調べるのが手間なため。前回の設計の「版を固定して入れる」を改める。
- 新しい版で sandbox が効かなくなるおそれには、ビルドの中で確かめて止める形で備える。
- 「実際に塞がれるか」は、版が「確かめた版」と違うときに起動時に知らせる（止めない）。canary は保守者が手で回す。

## 判断（設計者の判断。保守者が読んで直せる）

- **ビルドの中の確認の形**: ビルドの RUN の中で、一時の `COPILOT_HOME` に、起動口が実際に書くのと同じ設定（雛形に、起動口が起動のたびに足す `sandbox.userPolicy.filesystem.readonlyPaths` を仮の値〈例: `["/workspace"]`〉で足したもの）を置き、2 のコマンドで `--list --json` を取る。入力の設定の葉（末端の項目）が全部、出力に同じ値で出ていなければ ERROR で止める（どの項目が違ったかを出す）。項目が捨てられれば、出力から消えるので止まる。一時のディレクトリは RUN の中で消す。
  - `readonlyPaths` も含めるのは、雛形には無いが「作業ディレクトリは読めるが書けない」を担う項目だから（2026-11-09 の builder check の指摘）。起動口の組み立てと同じものを確かめるため、組み立ての処理を起動口と確認で共有するか、同じ形を確認の側で再現するかは作る人に任せる。ただし、ずれたらテストで分かるようにする。
  - 比べ方は「入力の葉が出力に全部あって、値が同じ」にする（出力に余分な項目があっても止めない）。4 の「既定値は出ない」は 1.0.103 の観測で、新しい版が既定値も出すようになっても、それだけでビルドが壊れないようにするため。余分に出た項目のゆるい既定値は、この確認では拾わない（下の「拾えないもの」）。
  - 確認を飛ばす口（環境変数など）は作らない。新しい版で `config` の形が変わって確認が通らなくなったら、通る版に番号で固定して逃げ、c3c 側の確認を直す。境界を弱める口を足さないため。
- **この確認で拾えないもの**（文書に書く）: 項目名と値はそのままで意味や挙動が変わった場合、新しい版で足された項目の既定値がゆるい場合、MXC の backend の変更。これらは canary でしか分からない。
- **「確かめた版」の置き場**: 起動口 `copilot-launcher.sh` の `readonly` の定数（例: `readonly VERIFIED_COPILOT_VERSION=1.0.103`）にする。新しいファイルを足さないので、`ASSET_HASH_TARGETS` は増えない（起動口を変えるので、既存のドリフトの WARNING は今までどおり出る）。上げるのは、保守者が新しい版で canary に合格した後の PR。
- **起動時の比較**: 起動口が、Copilot の `package.json` の `version` を読み、定数と違えば、stderr に WARNING を 1 回出して起動を続ける。`latest` か番号での固定かは見ない（番号で固定した版でも、確かめた版と違えば出す）。確かめていない版であることは指定の仕方によらず同じで、起動口がビルドの指定を知るための新しい入力（ラベルやファイル）を足さずに済むため。確かめた版と同じ版では出さない。文面には、入っている版、確かめた版、canary を回す案内（README の該当の節）を入れる。`package.json` が読めない・版が取れないときは、起動口の今の fail-closed の方針に合わせて ERROR で止める（実体の欠落は既存の検査でも止まる）。
- **キャッシュ**: `c3c` の `run_explicit_build()` に、`codex_cachebust` と同じ形の `copilot_cachebust` を足し、`copilot-version.txt` が `latest` のときだけ時刻にする。Dockerfile の Copilot の区間に `ARG COPILOT_CACHEBUST=pinned` を置き、RUN の先頭で echo する（Codex と同じ）。
- **書式の検査**: `Dockerfile.claude` と `guard_build_input_defaults()` の両方で、`^([0-9]+\.[0-9]+\.[0-9]+|latest)$` を受ける。`latest` のときは、Dockerfile の「入った版が指定と一致」の検査を、「入った版が `X.Y.Z` の形」の検査に替える。ビルドのログの INFO の行に、解決した版を出す。
- **c3c 自身の設定**: 保守者のローカルの `.c3c/copilot-version.txt`（`.gitignore` 済み）を `latest` にするのは保守者の手で行う。`.claude/AGENTS.md` のローカル専用ファイルの台帳の行（今は「2026-11-09 から 1.0.103」）も合わせて直す（ops のリポジトリ）。

## 作る人に任せること

- 確認の処理を Dockerfile の RUN に直接書くか、小さな検査用のスクリプト（`python3 -I` など）に分けるか。分けるなら、`docs/development-invariants.md` の書き方（root 所有、固定パス、`source` しない）に合わせる。
- WARNING の正確な文面と、`--check` にも同じ知らせ（INFO か WARN）を出すか。
- テストの置き方（`tests/test_copilot_launcher.py`・`tests/test_c3c_config.py`・`test-build.sh` の全体実行）。全体実行では、`latest` でビルドが通ること、雛形の項目を 1 つ捨てる版を模して確認が止めることを確かめたい。

## 直す文書

- README「利用側プロジェクトの設定」の `copilot-version.txt` の行と段落、「Copilot CLI を使う」節（`latest`、ビルドの中の確認、起動時の WARNING、canary を回す案内、拾えないもの）、「変更後の確認」節。
- `docs/development-invariants.md` の「Dockerfile の `# >>> c3c copilot` の区間と `copilot-version.txt`」（「`latest` を受けない（CACHEBUST を足さない）」を改める）と、`copilot-launcher.sh` の項。
- 前回の設計の文書と計画は、当時の記録として書き換えない。
