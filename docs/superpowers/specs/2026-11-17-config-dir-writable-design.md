# `~/.config` を node が書けるようにする（#275）の設計

## 目的と理由

対話のコンテナで `/home/node/.config` が root 所有になり、node が書けない。秘密のマウント（`compose.yml` の `${SECRETS_DIR:-/dev/null}:/home/node/.config/c3c/secrets:ro`）の親を、イメージに無いためランタイムが root で作るのが原因。ブラウザ（Chrome・Brave・Firefox）は `$XDG_CONFIG_HOME`（既定 `~/.config`）の下に設定を作れず、起動直後に落ちる。ほかのツールも `~/.config` に書けない。利用側（findsummits）が待っている。

## 目標・非目標・反目標

- 目標: 対話のコンテナで、node が `~/.config` の下に新しいディレクトリを作れる。
- 非目標: 秘密のマウント先（`~/.config/c3c/secrets`）を変えること。`XDG_CONFIG_HOME` の既定を変えること。
- 反目標（動いても失敗）: node（あるいは node で動くエージェント）が `~/.config/c3c` の名前を変える・消す・差し替えることで、秘密を別のパスに見せられるようになること。Copilot の sandbox は `copilot-settings.json` の `deniedPaths` で、秘密を `/home/node/.config/c3c/secrets` のパスだけで隠しているため（#259 の「秘密を別の位置に見せない」と同じ理由）。守るのは `~/.config/c3c` の改名・削除・差し替えに限る。`~/.config` そのものは、今のイメージでも node が同じ親（`/home/node`、node 所有）の中で改名でき、変更の後は別の親の下へも移せる（2026-11-17 実測）。これは既知の限界として塞がない（2026-11-17 持ち主の判断。改名できるのは秘密を既に読める sandbox の外の node だけで、sandbox の中の Copilot からは `/home/node` が見えないため）。

## 制約

- `docs/development-invariants.md` の秘密のマウントの項（`/home/node/.config/c3c/secrets` だけに `:ro`）を変えない。
- `SECRETS_DIR` が未設定のときは `/dev/null` をマウントするので、イメージで `secrets` のディレクトリを先に作らない（ディレクトリの上にキャラクタデバイスを bind することになり失敗するおそれ）。

## 方式の候補

1. **イメージで `~/.config` を `/tmp` と同じ形（root 所有・`1777`・sticky）にし、`~/.config/c3c` を root 所有の `755` で先に作る**（持ち主が選択）。node は `~/.config` の下に作れ、sticky のため root 所有の `c3c` の改名・削除はできない。2026-11-17 に findsummits のイメージで実測（node で `mkdir ~/.config/google-chrome` は成功、`mv c3c x` は `Operation not permitted`、`rm -rf c3c` は `Permission denied`）。
2. `~/.config` を node 所有にする（Issue の案）。node が `c3c` を改名でき、反目標に当たるので採らない。
3. 秘密のマウント先を `~/.config` の外へ移す。公開しているパスが変わり、利用側の移行が要るので採らない。

## 決めたこと

- `Dockerfile.claude` で `USER node` の前に、root で `/home/node/.config`（`root:root 1777`）と `/home/node/.config/c3c`（`root:root 755`）を作る。`secrets` は作らない。
- 不変条件の文書に、この形（sticky と root 所有の `c3c`）を崩さないことと理由を足す。
- README の Copilot の受け入れ手順の「`/home/node/.config` には node が新しいディレクトリを作れない」の記述を直す。
- 既存のイメージは `-b` で作り直すまで直らない（利用者から見える既定の挙動が変わるので、タグの提案の対象）。

## 実装者に任せること（計画で決めた）

- 検査の置き場: `test-build.sh` で確かめる。`--build-only` でイメージの `~/.config`・`~/.config/c3c` の所有者・モード、node での作成可、`c3c` の改名・削除不可を見る。`--config-ro-only` で `SECRETS_DIR` を設定した組と未設定の組を見る。層 2（`run_validator_layer2`）で `Dockerfile.claude` の `install -d` の行が `USER node` より前にあることを静的に見る。
- Copilot の受け入れ（`tests/copilot-canary.sh`）は変えない。README の手順の文だけを直す。
