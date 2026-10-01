# #190 Codex の起動時の更新確認をイメージ全体で無効にする

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 名前で呼ばれる `codex`（ログインシェル、`podman exec`、Claude 経路の Bash ツール）でも、起動時の更新確認が出ないようにする。

**Architecture:** Codex の管理側の要件ファイル `/etc/codex/requirements.toml` に `check_for_update_on_startup = false` を書き、root 所有でイメージに焼き込む。要件の値は、CLI の `-c`・user・project の設定値を置き換える（上流の仕様）。そのため、名前で呼ぶ起動も本起動も 1 ファイルで止まり、node はこのファイルを書き換えられない。`entrypoint.sh` の本起動の `-c 'check_for_update_on_startup=false'`（#183）は残す。

**Tech Stack:** Dockerfile（bash の RUN）、`test-build.sh`、README / `docs/development-invariants.md`。

**計画者:** Opus 5.5（claude-opus-5-5。実効モデルは計画の確定時に transcript の `.message.model` で確かめる）。

**要件:** [#190](https://github.com/jj1xgo/c3c/issues/190)。調査結果は [#190 のコメント](https://github.com/jj1xgo/c3c/issues/190#issuecomment-5924363533)。

## 背景

#183（PR #189、v17.0.1）で、`c3c codex` の本起動には更新確認の抑止が付いた。しかし、名前で `codex` を対話起動した場合には付かない（README「イメージの変更」節に限界として記載済み）。そこで「y」と答えると、#183 と同じく更新に失敗し、起動できなくなりうる。Claude Code が `DISABLE_AUTOUPDATER` でイメージ全体の自動更新を止めているのと同じ扱いにする。

## 一次情報（2026-10-01 に確認済み）

- 上流 rust-v0.159.3 の `codex-rs/config/src/loader/mod.rs`: Unix では system の requirements を `/etc/codex/requirements.toml` から読む。これより優先度の高い cloud 管理の要件層もある（c3c は使っていない）。
- 同版の `codex-rs/core/src/config/requirements.rs` の `apply_to_config`: `apply_exact!(check_for_update_on_startup)` で、設定された値を要件の値で置き換える。値が食い違うと、`Configured value for check_for_update_on_startup is overridden by the required value false from /etc/codex/requirements.toml.` という起動時の警告が出る。
- 同版の `codex-rs/tui/src/updates.rs` の `get_upgrade_version` と `get_upgrade_version_for_popup`: どちらも `config.check_for_update_on_startup` が false なら、確認とポップアップより前に戻る。
- 同版の `codex-rs/tui/src/updates_cache.rs`: キャッシュは `CODEX_HOME/version.json`。中身は `latest_version`・RFC3339 の `last_checked_at`・任意の `dismissed_version` で、確認の周期は 20 時間。
- 同版の `codex-rs/cli/src/doctor/updates.rs` と `doctor.rs`: `codex doctor --json` の `checks["updates.status"].details["check for update on startup"]` に、同じ `config.check_for_update_on_startup` の値を**文字列**（`"true"` / `"false"`）で出す。文字列であることは、host の 0.159.3 の実出力でも確認した。
- 上流のソース履歴: `ConfigRequirementsToml` が `check_for_update_on_startup` を持つのは rust-v0.146.0 以降。rust-v0.145.0 の `ConfigRequirementsToml` には `deny_unknown_fields` が無く、未知のキーは無視される（静的に読んだだけで、実測していない）。
- 実測（host、c3c のイメージ 0.159.3 と 0.156.0。ファイルを `:ro` で載せ、`--network none`、実行ユーザーは node、使い捨ての `CODEX_HOME`）:

  | 条件 | 実効値 |
  |---|---|
  | 要件のみ | false |
  | 要件 + `-c …=true` | false |
  | 要件 + user の `config.toml` が true | false |

  値が一致する場合（`-c …=false`、または指定なし）は、上の警告が出ない。
- 案 1（起動口で `-c` を前置する）は採らない。後から指定した `-c` が勝つので、呼び出し側が true を付ければ打ち消せる（host の 0.159.3 で実測）。
- 案 2（環境変数）は採らない。0.159.3 には、更新確認を止める環境変数が無かった。

## 決定事項

1. 要件ファイルは `Dockerfile.claude` の中で生成し、別のアセットファイルは作らない。
   - 理由: `Dockerfile.claude` は既に境界アセットのハッシュ対象（`c3c` の `ASSET_HASH_TARGETS`）なので、旧イメージでは追加の配線なしにドリフトの WARNING が出る。新しいファイル名を `resolve_asset_source`・`ASSET_HASH_TARGETS`・`stage_build_context` と `test-build.sh` の staging に足さずに済む。
2. 区切り `# >>> c3c codex-requirements` / `# <<< c3c codex-requirements` を付けた RUN を、`# <<< c3c codex-launcher` の直後、`USER node` より前に置く。
   - opt-out の判定はほかの Codex の RUN と同じにする（`tr -d '[:space:]'` で正規化し、空なら何も作らない）。
3. 次の場合はビルドを止める（fail-closed）。上書き・追記・chmod で直すことはしない。
   - base image が既に `/etc/codex/requirements.toml` を持っている（symlink を含む）。
   - 既存の `/etc/codex` が、symlink でない root:root 0755 のディレクトリではない。
   - 理由: base image の管理ポリシーを黙って消さない。ビルドが通ったときの配置を、probe が要求する配置（root:root 0755 / 0644）と一致させる。
4. ファイルの内容は次の 2 行に固定する。ディレクトリは root:root 0755、ファイルは root:root 0644。

   ```toml
   # c3c: 起動時の更新確認を無効にする（#190）。版の更新は -b の再ビルドで行う。
   check_for_update_on_startup = false
   ```

5. `entrypoint.sh` は変更しない。本起動の `-c 'check_for_update_on_startup=false'` は、要件ファイルの無い旧イメージでも効く多重の防御として残す。値が一致するので警告は出ない（実測済み）。
6. 更新確認の抑止は利便性のための設定とし、新しいセキュリティ不変条件にはしない（#183 と同じ）。ただし、後から RUN を動かして壊さないよう、置き場所と fail-closed の条件は `docs/development-invariants.md` に配置の制約として書く。
7. `IMAGE_LAYOUT_VERSION`（`c3c:34`、現在 2）は上げない。
   - 理由: launcher も `entrypoint.sh` も、新しいパスに依存しない。旧イメージは本起動の `-c` で守られ、名前で呼ぶ起動が従来どおりになるだけで、起動は壊れない。再ビルドはドリフトの WARNING が案内する。
8. 確認済みの版は、受入で確かめた latest の版と 0.156.0。0.146.0〜0.155.x は上流のソースを静的に読んだだけで、実測していない。0.145.0 以前はキーが無視されると読んでいるが、未確認。README では「確認した版」と「上流のソースで読んだ範囲」を分けて書く。
9. 保証文は「対応版では、通常の `-c`・user・project の設定では再有効化できず、node はこのファイルを書き換えられない」に限定する。cloud 管理の要件層との組み合わせと、旧版での挙動は保証しない。

## Global Constraints

- 日本語で書く。技術用語・コマンド名・パスは英語のまま。
- シェルは bash。編集したターンのうちに `./lint.sh` を実行し、rc 0・警告ゼロを確認する。
- 挙動を変えたら、README の該当節も同じ commit で更新する（root `AGENTS.md`）。このため、Task 1 と Task 2 は 1 つの commit にする。
- `Dockerfile.claude` の既存の不変条件（`docs/development-invariants.md` の `Dockerfile.claude` 節）を崩さない。特に、codex-bwrap と codex-launcher の RUN の順序・区切り・中身は変えない。
- 他セッションの未追跡ファイル（`.c3c/codex-version.txt`、`tests/__pycache__/`）を add しない。
- 認証情報を表示・解析・コピーしない。受入で更新は実行しない。

## Review Focus

1. 名前で起動した対話 TUI（`podman exec` とログインシェル）で、実際に更新案内が出ないこと。`doctor` の実効値だけでは代わりにしない。Task 3 Step 3 で行う。
2. 本起動（通常・read-only）が、更新案内の出る条件でも案内を出さず、同じ argv で起動し、上書きの警告を出さないこと。Task 3 Step 2 で行う。
3. ベースイメージに既に `/etc/codex/requirements.toml` がある場合、または `/etc/codex` が 0755 以外の場合に、ビルドが止まること。Task 1 Step 6 の手動ビルドで確かめる。
4. opt-out のイメージに `/etc/codex` が作られないこと。Task 1 で行う。
5. `latest` の上流で `doctor --json` の形が変わったときに、CI の probe が赤になって気づけること（黙って通らないこと）。Task 1 の probe は、キーが無いか、timeout したら失敗させる。

---

### Task 1: 要件ファイルを焼き込み、ビルド検査を足す

**Files:**
- Modify: `Dockerfile.claude`（`# <<< c3c codex-launcher` の直後に新しい RUN を足す。現在 305 行目付近）
- Modify: `test-build.sh`
  - `--build-only` の Codex 起動口 probe の直後（現在 2413〜2414 行目付近）
  - opt-out の「codex が入っていない」check の 2 か所（成功時の分岐が現在 2550〜2551 行目付近、staging 失敗時の分岐が現在 2557 行目付近）

**Interfaces:**
- Produces: イメージ内の `/etc/codex/requirements.toml`（root:root 0644）と `/etc/codex`（root:root 0755）。Task 2 の文書と Task 3 の受入が、この配置と内容を前提にする。

- [ ] **Step 1: test-build.sh に probe を足す（先に書く）**

`CODEX_LAUNCHER_PROBE` の `check "Codex 起動口…"` の直後に、次を足す。

```bash
# Codex の起動時の更新確認を要件ファイルで無効にする（#190）。名前で呼ぶ codex も本起動も、-c や user の
# config.toml で true にしても false のままになる。doctor はネットワークも認証も無いと非ゼロで終わるので
# 終了コードでは判定しない。timeout（124）だけは失敗にし、JSON にキーが無ければ（上流の出力形式の変更）失敗させる。
# shellcheck disable=SC2016  # コンテナ内の sh で評価する
CODEX_REQUIREMENTS_PROBE='set -e
d=/etc/codex; f=/etc/codex/requirements.toml
[ -d "$d" ] && ! [ -L "$d" ] || { echo "/etc/codex が symlink でないディレクトリではない"; exit 1; }
[ "$(stat -c %u:%g:%a "$d")" = 0:0:755 ] || { echo "/etc/codex が root:root 0755 ではない: $(stat -c %u:%g:%a "$d")"; exit 1; }
[ -f "$f" ] && ! [ -L "$f" ] || { echo "要件ファイルが symlink でない通常ファイルではない"; exit 1; }
[ "$(stat -c %u:%g:%a "$f")" = 0:0:644 ] || { echo "要件ファイルが root:root 0644 ではない: $(stat -c %u:%g:%a "$f")"; exit 1; }
! [ -w "$f" ] && ! [ -w "$d" ] || { echo "要件ファイルかそのディレクトリが node から書込可"; exit 1; }
[ "$(grep -v "^#" "$f")" = "check_for_update_on_startup = false" ] || { echo "要件ファイルの設定行が想定と違う"; cat "$f"; exit 1; }
home="$(mktemp -d)"
printf "check_for_update_on_startup = true\n" > "$home/config.toml"
rc=0
CODEX_HOME="$home" timeout 60 codex -c check_for_update_on_startup=true doctor --json > "$home/doctor.json" 2>/dev/null || rc=$?
[ "$rc" != 124 ] || { echo "codex doctor が 60 秒で終わらない"; exit 1; }
v="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[\"checks\"][\"updates.status\"][\"details\"][\"check for update on startup\"])" "$home/doctor.json")" \
  || { echo "codex doctor --json（rc=$rc）から更新確認の実効値を読めない（上流の出力形式の変更を疑う）"; exit 1; }
[ "$v" = false ] || { echo "要件ファイルがあるのに更新確認の実効値が $v"; exit 1; }
[ "$(id -u)" != 0 ]'
check "Codex の更新確認の要件ファイル（root:root・node から書込不可・固定内容・-c と user 設定の true より優先）" \
  podman run --rm --network=none "$IMAGE" sh -c "$CODEX_REQUIREMENTS_PROBE"
```

opt-out の check を、成功時の分岐では次のように置き換える（式に `&& [ ! -e /etc/codex ]` を足し、名前を変える）。

```bash
  check "Codex opt-out: codex が入っていない（起動口・同梱 bubblewrap・要件ファイルなし）" \
    podman run --rm --network=none "$OPTOUT_IMAGE" sh -c '! command -v codex >/dev/null && [ ! -e /usr/local/bin/codex ] && [ ! -e /usr/local/libexec/c3c/codex-bwrap ] && [ ! -e /etc/codex ]'
```

staging 失敗時の分岐（`else` 側）の同名の check も、名前を揃える。

```bash
  check "Codex opt-out: codex が入っていない（起動口・同梱 bubblewrap・要件ファイルなし）" false
```

- [ ] **Step 2: probe が赤になることを確かめる**

Run: `./test-build.sh --build-only`（host。Podman が要る）
Expected: 新しい check だけが「/etc/codex が symlink でないディレクトリではない」で FAIL し、既存の check はすべて PASS する。

- [ ] **Step 3: Dockerfile.claude に RUN を足す**

`# <<< c3c codex-launcher` の直後に、次を足す。

```dockerfile
# >>> c3c codex-requirements
# 名前で呼ぶ codex（ログインシェル、podman exec、Claude 経路の Bash ツール）も含め、起動時の更新確認を
# 無効にする（#190）。Codex の管理側の要件ファイル（Unix は /etc/codex/requirements.toml）の値は、-c・user・
# project の設定値を置き換える。root 所有なので node は書き換えられない。版の更新は -b の再ビルドで行う。
# base image が既に要件ファイルを持っていればその管理ポリシーを黙って消さないよう、既存の /etc/codex が
# root:root 0755 のディレクトリでなければ配置を probe と揃えるよう、どちらもビルドを止める（直さない）。
# opt-out では何も作らない。
RUN set -e; \
    CODEX_VERSION="$(tr -d '[:space:]' < /tmp/codex-version.txt)"; \
    if [ -z "$CODEX_VERSION" ]; then \
      echo "INFO: Codex は opt-out のため更新確認の要件ファイルを置きません"; \
    else \
      d=/etc/codex; f=/etc/codex/requirements.toml; \
      if [ -e "$f" ] || [ -L "$f" ]; then \
        echo "ERROR: $f が既にあります（base image の管理ポリシー）。c3c は上書きしません" >&2; exit 1; \
      fi; \
      if [ -e "$d" ] || [ -L "$d" ]; then \
        [ -d "$d" ] && ! [ -L "$d" ] || { echo "ERROR: $d が symlink でないディレクトリではありません" >&2; exit 1; }; \
        mode="$(stat -c %u:%g:%a "$d")" || { echo "ERROR: $d の所有者・mode を検査できません" >&2; exit 1; }; \
        [ "$mode" = 0:0:755 ] || { echo "ERROR: $d が root:root 0755 ではありません（$mode）" >&2; exit 1; }; \
      else \
        install -d -o root -g root -m 0755 "$d"; \
      fi; \
      printf '%s\n' '# c3c: 起動時の更新確認を無効にする（#190）。版の更新は -b の再ビルドで行う。' \
        'check_for_update_on_startup = false' > "$f"; \
      chown root:root "$f"; chmod 0644 "$f"; \
      echo "INFO: Codex の更新確認を無効にする要件ファイル: $f"; \
    fi
# <<< c3c codex-requirements
```

`/tmp/codex-version.txt` は 160 行目の `COPY` で置かれ、`Dockerfile.claude` の中では消されない（計画時に `grep -n codex-version.txt Dockerfile.claude` で確認済み）。codex-bwrap・codex-launcher の RUN と同じく、そのまま読める。

- [ ] **Step 4: probe が緑になることを確かめる**

Run: `./test-build.sh --build-only`
Expected: 新しい check を含め全件 PASS、FAIL=0。

Run: `./test-build.sh`（引数なしの全体実行）
Expected: opt-out の check を含め全件 PASS、FAIL=0。

- [ ] **Step 5: lint**

Run: `./lint.sh`
Expected: rc 0、警告ゼロ（Compose 検証を含む）。commit は Task 2 の後にまとめて行う。

- [ ] **Step 6: base image に既存の要件ファイルがある場合の fail-closed を確かめる（Review Focus 3）**

`c3c` の `guard_base_image()` は、`base-image.txt` に docker.io の debian 公式イメージしか許さない。このため、既存の要件ファイルや異なる mode の `/etc/codex` に当たる経路は、debian の tag の違いか `packages.txt` の apt パッケージに限られ、通常は到達しない。ガードは安価なので残し、検証は手動ビルドで行う（`test-build.sh` に負のビルドを足す価値は無い）。

前提: Task 3 Step 2 で、Codex を導入する（`codex-version.txt` が空でない）fixture を `c3c -b` で staging 済みであること。opt-out の fixture ではガードに到達しない。この Step は Task 3 Step 2 の後に行う。

```bash
ctx=.build-context/<latest の fixture の PROJECT_NAME>
[ -s "$ctx/codex-version.txt" ] || { echo "fixture が opt-out です"; exit 1; }
for case in file:'mkdir -p /etc/codex && printf "x = 1\\n" > /etc/codex/requirements.toml' \
            mode:'mkdir -p /etc/codex && chmod 0775 /etc/codex'; do
  name="${case%%:*}"; cmd="${case#*:}"
  tmp="$(mktemp -d)"
  printf 'FROM debian:stable\nRUN %s\n' "$cmd" > "$tmp/Containerfile"
  podman build -t "localhost/c3c-190-prereq-$name" "$tmp"
  podman build -f Dockerfile.claude --build-arg "BASE_IMAGE=localhost/c3c-190-prereq-$name" \
    -t "localhost/c3c-190-prereq-$name-test" "$ctx" > "$tmp/build.log" 2>&1; echo "$name rc=$?"
  grep -E "ERROR: /etc/codex" "$tmp/build.log"
done
podman rmi -f localhost/c3c-190-prereq-file localhost/c3c-190-prereq-mode \
  localhost/c3c-190-prereq-file-test localhost/c3c-190-prereq-mode-test 2>/dev/null || true
```

Expected:
- `file rc=` が非ゼロで、`ERROR: /etc/codex/requirements.toml が既にあります（base image の管理ポリシー）。c3c は上書きしません` が出る。
- `mode rc=` が非ゼロで、`ERROR: /etc/codex が root:root 0755 ではありません（0:0:775）` が出る。

実行前に `cat "$tmp/Containerfile"` で、2 行目が `RUN mkdir -p /etc/codex && …` になっていることを確かめる（`case` の値はシングルクォートの中なので、`&&` はそのまま残る）。実行できなかった場合は `not run` と理由を記録する。

### Task 2: 文書を更新し、Task 1 とまとめて commit する

**Files:**
- Modify: `README.md`
  - 「イメージの変更」節の #183 の段落（現在 622 行目）
  - 「アーキテクチャ」の `Dockerfile.claude` 項（現在 573 行目）
  - 「変更後の確認」の Codex 本起動の段落（現在 777 行目）と、その直後
- Modify: `docs/development-invariants.md`（`Dockerfile.claude` 節の Codex 起動口の項の直後。現在 74 行目の後）

**Interfaces:**
- Consumes: Task 1 の配置（`/etc/codex/requirements.toml`、root:root 0644、opt-out では作らない、既存なら止める）。

- [ ] **Step 1: README「イメージの変更」の段落を置き換える**

現在の 622 行目の段落全体を、次に置き換える。「確認した版」の文はここでは書かず、Task 3 Step 5 で足す。

> Codex CLI の起動時の更新確認は、イメージに焼き込む要件ファイル `/etc/codex/requirements.toml`（root 所有、`check_for_update_on_startup = false`）で無効にしている（[#183](https://github.com/jj1xgo/c3c/issues/183)、[#190](https://github.com/jj1xgo/c3c/issues/190)）。Codex は要件の値で `-c`・user・project の設定値を置き換えるため、`c3c codex` の本起動だけでなく、ログインシェルや `podman exec` から名前で呼ぶ対話 `codex` にも効く。対応版では、通常の `-c`・user・project の設定では再び有効にできず、node はこのファイルを書き換えられない（Codex の cloud 管理の要件と組み合わせた場合は対象外）。本起動は、要件ファイルの無い旧イメージにも備えて `-c 'check_for_update_on_startup=false'` も渡す。版の更新は `-b` の再ビルドで行う。固定版を指定している場合は `.c3c/codex-version.txt` の版を変更してから再ビルドする。`latest` はビルド時点の最新版を入れる指定で、起動するたびに最新版へ更新するものではない。既存イメージへの反映には再ビルドが必要で、境界アセットのドリフト WARNING が案内する。base image が既に `/etc/codex/requirements.toml` を持っている場合と、`/etc/codex` が root:root 0755 のディレクトリでない場合は、ビルドを止める（base image の管理ポリシーを消さず、配置を直さない）。opt-out（空の `codex-version.txt`）では作らない。

- [ ] **Step 2: README「アーキテクチャ」の Dockerfile 項に 1 文足す**

573 行目の「`node-version.txt` ブロックの直後には、…詳細は内部運用issue参照）。」の直後に、次を足す。

> Codex を導入したイメージでは、起動時の更新確認を無効にする要件ファイル `/etc/codex/requirements.toml` を root 所有で置く（後述「イメージの変更」節）。

- [ ] **Step 3: README「変更後の確認」の 777 行目を直し、段落を足す**

777 行目の次の文は、要件ファイルの導入後は同じイメージで成立しない（直接起動した対話 CLI でも案内が出なくなる）。

> 更新確認の抑止は argv の一致だけで判断せず、使い捨ての専用 home と同一の更新キャッシュを使い、本起動では更新案内が出ず、同じイメージから直接起動した対話 CLI では出る対照で確認する。

これを次に置き換える。

> 更新確認の抑止は argv の一致だけで判断しない。使い捨ての専用 home と同一の更新キャッシュを使い、本起動では更新案内が出ないことと、要件ファイルの無いイメージ（要件ファイルの導入前にビルドしたイメージ）から名前で呼んだ対話 CLI では案内が出る対照で確認する。

777 行目の段落の直後に、次の段落を足す。

> Codex の要件ファイル（`Dockerfile.claude` の `# >>> c3c codex-requirements` 区切りの RUN）を変更した場合は、`--build-only`（所有者・mode・node から書込不可・固定内容と、`-c`・user 設定の true より要件が優先されることの `codex doctor --json` での確認）と、opt-out のイメージに `/etc/codex` が無いことを確かめる引数なしの全体実行を行う。更新確認の抑止は `doctor` の実効値だけで判断しない。使い捨ての専用 home と同一の更新キャッシュを使い、名前で呼ぶ対話 `codex`（`podman exec` とログインシェル）と本起動（通常・read-only）のどれでも更新案内が出ないことを確認する。対照には、要件ファイルの導入前にビルドした同じ版のイメージで、名前で呼んだ対話 `codex` に案内が出ることを確認する（旧イメージの本起動は #183 の `-c` で抑止されるので、対照にならない）。Codex 0.156.0 を固定した fixture でも確認する。base image に既存の要件ファイルがある場合と `/etc/codex` が 0755 でない場合にビルドが止まることは、手動ビルドで確認する。未実施の項目は `not run` と理由を報告する。

- [ ] **Step 4: docs/development-invariants.md に項を足す**

74 行目（Codex 起動口 #152 の項）の直後に、次を足す。

> - Codex の更新確認の要件ファイル（#190）: `# >>> c3c codex-requirements` 区切りの RUN を codex-launcher の RUN より後・`USER node` の前に置き、`/etc/codex/requirements.toml` を root:root 0644（ディレクトリは root:root 0755）で作る。opt-out の判定は Codex の install RUN と同じ正規化と `set -e`。次の場合はビルドを止める（上書き・追記・chmod で直さない）: base image が既に要件ファイルを持つ（symlink を含む）、既存の `/etc/codex` が symlink でない root:root 0755 のディレクトリでない。更新確認の抑止は利便性の設定で、セキュリティ境界ではない。ファイルを `Dockerfile.claude` の中で生成するのは、境界アセットのハッシュ（`Dockerfile.claude`）でドリフトを検出させるためである。別のアセットファイルに切り出すなら、`ASSET_HASH_TARGETS` と staging にも足す。`IMAGE_LAYOUT_VERSION` は上げていない（launcher と `entrypoint.sh` はこのパスに依存せず、旧イメージは本起動の `-c` で守られるため）。`test-build.sh --build-only` が、配置と、`-c`・user 設定より要件が優先されることを検査する。

- [ ] **Step 5: lint**

Run: `./lint.sh`
Expected: rc 0、警告ゼロ。

- [ ] **Step 6: Commit（Task 1 と Task 2 をまとめる）**

```bash
git add Dockerfile.claude test-build.sh README.md docs/development-invariants.md
git commit -m "fix: Codex の起動時の更新確認を要件ファイルでイメージ全体に無効にする"
```

### Task 3: 実機受入

**Files:**
- Modify: README の「確認した版」（Task 2 Step 1 の段落の末尾）、本計画ファイル（結果の記録）

専用の fixture を使い、他セッションのイメージや設定を上書きしない。認証情報は持ち込まず、表示・解析・コピーしない。更新は実行しない。

fixture は 2 つ用意する。
- A: `codex-version.txt` を置かない（同梱 default の latest）。
- B: `.c3c/codex-version.txt` に `0.156.0` と書く。

どちらも、`.c3c/env` の `CODEX_DIR` に使い捨てのディレクトリを指定する（#183 の受入と同じ方法）。

更新キャッシュの作成（各試行の直前に毎回作り直す）:

```bash
mkcache() { printf '{"latest_version":"999.0.0","last_checked_at":"%s","dismissed_version":null}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$1/version.json"; }
```

TUI の観測（疑似端末で 20 秒だけ動かし、画面に出た文言で判定する）:

- 更新案内の見出しは `Update available`（上流 rust-v0.159.3 の `codex-rs/tui/src/update_prompt.rs` とその snapshot。0.156.0 の同ファイルにも同じ文字列がある）。
- 認証の無い home では、案内が無ければサインイン画面（`Sign in with ChatGPT`、上流の `codex-rs/tui/src/onboarding/auth.rs`）へ進む。#183 の受入でも、案内の後・案内なしのどちらでもサインイン画面になった。
- 判定は 3 値にする。サインイン画面に到達していない「案内なし」は、抑止の成功と区別する。

```bash
observe() {
  log="$1"; shift
  sleep 30 | timeout 20 script -qfc "$*" "$log" > /dev/null 2>&1; rc=$?
  screen="$(sed 's/\x1b\[[0-9;?]*[A-Za-z]//g' "$log")"
  if printf '%s' "$screen" | grep -q 'Update available'; then echo "BANNER (rc=$rc)"
  elif printf '%s' "$screen" | grep -q 'Sign in with ChatGPT'; then echo "NO-BANNER (sign-in reached, rc=$rc)"
  else echo "UNOBSERVED (rc=$rc)"; fi
}
```

`UNOBSERVED` は、起動の失敗か観測の失敗である。抑止の成功として数えず、ログを記録して計画側へ戻す。stdin は `sleep 30 |` で開いたままにする（`< /dev/null` だと、script が EOF で早く終わる版がある）。

`observe` の後に、試行で残ったコンテナが無いことを `podman ps --filter name=<fixture の PROJECT_NAME>` で確かめる。残っていれば `podman stop` する。

- [ ] **Step 1: 変更前のイメージを作って退避し、ドリフト WARNING を見る**

`main` の 181c1cc の worktree（`git worktree add <dir> 181c1cc`）の `c3c` で、fixture A と B を `-b` でビルドする。次に、それぞれのイメージを退避の tag に付け替える。

```bash
podman tag localhost/<A の PROJECT_NAME>_claude-auth-workspace:latest localhost/c3c-190-before-a:latest
podman tag localhost/<B の PROJECT_NAME>_claude-auth-workspace:latest localhost/c3c-190-before-b:latest
podman run --rm --network=none --entrypoint /usr/local/bin/codex localhost/c3c-190-before-a:latest --version
podman run --rm --network=none --entrypoint /usr/local/bin/codex localhost/c3c-190-before-b:latest --version
```

続けて、変更後の checkout の `c3c` で、再ビルドせずに `c3c --check <fixture A>` を実行する。
Expected: 境界アセットのドリフト WARNING が出る。

- [ ] **Step 2: 再ビルドと本起動（Review Focus 2）**

変更後の checkout の `c3c` で、fixture A を `-b` で再ビルドする。`podman run --rm --network=none --entrypoint /usr/local/bin/codex localhost/<A の PROJECT_NAME>_claude-auth-workspace:latest --version` が、Step 1 の `c3c-190-before-a` の版と同じであることを確かめる。違えば（その間に上流が出た）、Step 1 から A をやり直す。

通常起動と read-only 起動のそれぞれで、次を行う。

```bash
mkcache <A の CODEX_DIR>
observe /tmp/c3c-190-a-main.log "./c3c codex <fixture A>"
mkcache <A の CODEX_DIR>
observe /tmp/c3c-190-a-main-ro.log "./c3c codex --read-only <fixture A>"
```

起動中に、別の端末から `podman top <container> pid,args` で argv を記録する。20 秒では間に合わない場合は、Step 3 の 120 秒の起動（通常）と、同じ形の `./c3c codex --read-only <fixture A>` の 120 秒の起動で取る。
Expected:
- 通常と read-only のどちらも `NO-BANNER (sign-in reached …)`（`UNOBSERVED` は不成立として計画側へ戻す）。
- argv が #183 と同じ（sandbox・approval・trust override・末尾の `-c 'check_for_update_on_startup=false'`）。
- ログに `overridden by the required value` が無い。
- 試行後の `<A の CODEX_DIR>/version.json` の `dismissed_version` が null のままで、`last_checked_at` が試行前と同じ。

- [ ] **Step 3: 名前で呼ぶ対話 TUI での抑止と、変更前のイメージによる対照（Review Focus 1）**

コンテナの中で使う観測スクリプトを、host の使い捨てディレクトリに 1 つ作る。引数で起動のしかたを選ぶ（`named` は名前で `codex`、`login` はログインシェルから `codex`）。

```bash
probe_dir="$(mktemp -d)"
cat > "$probe_dir/named-probe.sh" <<'EOF'
#!/bin/sh
# 使い捨ての CODEX_HOME に 999.0.0 の更新キャッシュを置き、名前で codex を起動する（#190 の受入）。
h="$(mktemp -d)"
printf '{"latest_version":"999.0.0","last_checked_at":"%s","dismissed_version":null}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$h/version.json"
case "$1" in
  named) CODEX_HOME="$h" exec codex ;;
  login) CODEX_HOME="$h" exec bash -lc codex ;;
esac
EOF
chmod 0755 "$probe_dir/named-probe.sh"
```

変更後のイメージ（3 経路）:

```bash
img=localhost/<A の PROJECT_NAME>_claude-auth-workspace:latest
observe /tmp/c3c-190-a-named.log "podman run --rm -it --network=none -v $probe_dir/named-probe.sh:/tmp/named-probe.sh:ro,Z --entrypoint sh $img /tmp/named-probe.sh named"
observe /tmp/c3c-190-a-login.log "podman run --rm -it --network=none -v $probe_dir/named-probe.sh:/tmp/named-probe.sh:ro,Z --entrypoint sh $img /tmp/named-probe.sh login"
```

`podman exec` の経路では、本起動を 1 つ長めに動かしておき、そのコンテナに対して行う。スクリプトは `podman cp` でそのコンテナへ入れる。

```bash
(timeout 120 script -qfc "./c3c codex <fixture A>" /tmp/c3c-190-a-host.log < /dev/null > /dev/null 2>&1 &)
# コンテナ名を podman ps --filter name=<A の PROJECT_NAME> で確かめてから
podman cp "$probe_dir/named-probe.sh" <container>:/tmp/named-probe.sh
observe /tmp/c3c-190-a-exec.log "podman exec --user node -it <container> sh /tmp/named-probe.sh named"
```

対照（変更前のイメージ、同じ版）:

```bash
observe /tmp/c3c-190-before-a-named.log "podman run --rm -it --network=none -v $probe_dir/named-probe.sh:/tmp/named-probe.sh:ro,Z --entrypoint sh localhost/c3c-190-before-a:latest /tmp/named-probe.sh named"
```

Expected:
- 変更後の 3 経路（named・login・exec）は、どれも `NO-BANNER (sign-in reached …)`。
- 対照は `BANNER`。
- コンテナ内の使い捨てキャッシュはコンテナごと消えるので、試行後の値は見ない。各試行は毎回新しいキャッシュで始まるので、前の試行の dismissal が後の試行を汚すことはない。

対照が `BANNER` にならないか、変更後のどれかが `UNOBSERVED` なら、この確認は不成立と報告し、成功とは書かずに計画側へ戻す。実装者は新しい観測方法を設計しない。

- [ ] **Step 4: 0.156.0 の fixture**

fixture B で Step 2 と Step 3 を繰り返す。`img` は B のイメージ、対照は `localhost/c3c-190-before-b:latest` にする。
Expected: Step 2・3 と同じ。互換性に問題があれば実装を確定せず、計画側へ戻す。

- [ ] **Step 5: 記録と commit**

受入が成立した版だけを、Task 2 Step 1 の段落の末尾に次の形で足す。

> 確認した版: codex-cli <A の版>・0.156.0。要件ファイルでこの設定を扱えるのは、上流のソースでは rust-v0.146.0 以降（それより前の版はこのキーを無視すると読んでいるが、未確認）。

本計画の末尾に、次を分けて記録する。
- 上流コードの確認
- `doctor` の実効値（`--build-only` の probe）
- 実 argv
- 実 TUI の抑止と対照
- base image の fail-closed（Task 1 Step 6）

実測できなかった項目は `not run` と理由を書く。後片付けとして、`c3c-190-before-a`・`c3c-190-before-b` の tag と、181c1cc の worktree を消す。

```bash
git add README.md docs/superpowers/plans/2026-10-01-codex-update-check-requirements.md
git commit -m "docs: #190 の受入結果と確認した版を記録する"
```

## 検証のまとめ

- `./lint.sh`: rc 0、警告ゼロ（Compose を含む。host）。
- `./test-build.sh --build-only` と引数なしの全体実行: FAIL=0。`Dockerfile.claude` を変更するので、README「変更後の確認」節に従い両方を行う。
- `./test-build.sh --launcher-only`: FAIL=0。`entrypoint.sh` と起動口は変えないが、既存の回帰として実行する。
- 実機受入: Task 3。
- GitHub CI: PR 作成後に、run の headSha が PR の head と一致することを確かめる。

## レビューと公開

- 計画レビュー: 作成に関わっていない Codex と Claude の二重で行う。
  - Codex は `codex exec --model gpt-6-astra --sandbox read-only` を先に background で起動する（stdin は `< /dev/null`）。
  - Claude は `claude-review` skill の「計画・仕様案のレビューに流用するとき」の手順で行う（headless の `claude -p --model opus`、Read / Grep / Glob のみ）。
  - 実効モデルを記録する。
- 実装者は、持ち主の指定を受けてから編集する。区分が境界なので、PR 前の二重レビューを行い、Critical・Important に対応してから PR を作る。両レビュアーの全文は PR コメントに載せる。
- PR 後は、別の Claude の対話セッションへ、レビューとマージを引き継ぐ。
- タグ: 既定の挙動の変更（名前で呼ぶ codex の更新確認が止まる）で、CLI 引数と `.c3c/` の形式は変えない。v17.0.2（PATCH）を想定し、実装後に SemVer の基準で提案する。
- 計画ファイルは、承認後に `docs/superpowers/plans/2026-10-01-codex-update-check-requirements.md` へ置き、作業ブランチ（`fix/codex-update-check-requirements`）で commit する。

## Codex 実行条件

- sandbox: `workspace-write`。Podman と、レビューに必要な host の許可。
- ネットワーク: `-b` の再ビルド（npm・apt）と上流の照合に要る。編集と lint には要らない。
- sandbox 内で Podman が制限された場合は、許可を得て host で再実行する。スキップを検証の成功として扱わない。
- `/goal` は持ち主が明示した場合だけ開始する。

`/goal` に渡す文面: 「#190 の計画 `docs/superpowers/plans/2026-10-01-codex-update-check-requirements.md` を executing-plans で実装する。Dockerfile.claude に要件ファイルの RUN を足し、test-build.sh の probe と README・development-invariants を更新して 1 つの commit にする。他セッションの変更と未追跡ファイルに触れず、lint・test-build の --build-only と全体実行・実機受入（Task 3）を行い、未実施の項目を明記する。境界の PR 前二重レビューまで進め、未承認の push は行わない。」

区分: 境界 — 境界アセットである `Dockerfile.claude` に root 所有のファイル配置を足し、名前で呼ぶものを含むすべての Codex 起動の設定に効くため。抑止そのものはセキュリティ境界ではない。

推奨実装: Codex — 判定基準を上から当てた結果、基準 4 に該当する。

- 基準 1（コンテナ内でしか成立しない）には当たらないと判断した。受入はコンテナを起動して中を観測するが、操作はすべて host の checkout から `podman` と `c3c` で行う。c3c のコンテナ内セッションからは実行できない（コンテナ内に podman が無い）。#183 の同じ型の受入も、Codex が host で完了している。基準 1 は、c3c のコンテナの中のセッションで作業する必要がある場合（compose や firewall の起動確認をコンテナ内から行う、コンテナ内セッションから継続する）を指すと読んだ。
- 基準 2・3 にも当たらない。`~/.claude` 配下・hook・秘密の経路に触れず、RUN・probe・文書・受入の手順と Expected が逐語で確定していて、設計判断が残らない。
- この読みは計画者の解釈である。持ち主が基準 1 に当たると判断すれば、Claude（Sonnet）にする。実装者の確定は持ち主の指定による。

## 計画レビュー結果（2026-10-01）

- 計画者の実効モデル: claude-opus-5-5（transcript の `.message.model` で全応答を確認）。
- Codex: GPT-6 Astra（`gpt-6-astra`、reasoning `medium`。CLI のヘッダで確認）、計 3 巡。
  - 初回: 「修正後に渡せる」。Critical 0・Important 3・Minor 3。
    - Important: 既存の `/etc/codex` の許容条件が probe と食い違う。本起動の抑止を判別する受入が無い。推奨実装の理由が判定基準 1 を扱っていない。
  - 確認限定 1 巡目: Important 2 が残った。新規の Important が 2 件出た。
    - キャッシュの表示で誤って `BANNER` になる。
    - `\&\&`。これは修正前のコピーを渡したためで、ファイルは修正済みだった。
  - 確認限定 2 巡目: 全件解決。「実装に渡せる」。
  - 判定基準 1 の扱いは「計画者の解釈であり、持ち主の指定で確定する」ことに同意した。ただし、解釈そのものを規則上確定したとは承認していない。
- Claude: Opus 5.5（headless の `claude -p`、`modelUsage` は claude-opus-5-5）、計 2 巡。
  - 初回: 「修正後に渡せる」。Critical 0・Important 3・Minor 7。
    - Important: 対照に使う変更前イメージの退避と作り方が無い。対照で同じキャッシュを使えない。README 777 行目の手順が成立しなくなる。
  - 確認限定 1 巡目: 全件解決。「実装に渡せる」。新たに Minor 1 件（`\&\&`）が出て、反映済み。
- 未対応の Critical・Important・Minor は無い。レビューは静的な計画の照合であり、実装や実機受入の成功を意味しない。
