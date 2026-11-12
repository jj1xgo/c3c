# HOME_MOUNT / HOME_MOUNT_RO Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ホストの `$HOME` 配下のディレクトリを、コンテナの `/home/node/<HOME からの相対パス>` に rw（`HOME_MOUNT`）または `:ro`（`HOME_MOUNT_RO`）でつなぐ opt-in を足す（#259）。

**Architecture:** 既存の `guard_shared_home_alias()`・`guard_agents_dir()` と同じ「launcher が検証して export → 固定 compose override を `COMPOSE_OVERRIDE_ARGS` に積む」形。新しいガード 1 つ（`guard_home_mounts()`）が 2 つのキーをまとめて検証し、固定 override `compose.home-mount.yml`（rw）と `compose.home-mount-ro.yml`（ro）を選ぶ。

**Tech Stack:** bash（`c3c`）、podman compose の固定 override、`test-build.sh`（ダミー podman の launcher テストと実 podman のプローブ）、`lint.sh`。

**Spec:** `docs/superpowers/specs/2026-11-12-home-mount-design.md`（保守者承認 2026-11-12）。計画と spec の両方を読むこと。

## Context

findsummits がコンテナの中から Copilot の並走を起動したい。並走の予算の台帳（`flock` で追記する JSONL）・出力をホストとコンテナで同じファイルとして共有し、送る前の確認に使うファイルは読むだけで見せたい。保守者は、ホストの絶対パスをコンテナに増やさず、`~` から見て同じ位置で見せることを選んだ（spec「決まったこと」）。

作業ブランチは `feat/home-mount`（作成済み、`main` の `bbd09b9` から）。計画の承認の直後に、計画者が spec（未追跡）と、この計画を `docs/superpowers/plans/2026-11-12-home-mount.md` に写したものを 1 つの commit にする（公開の置き場。ホストのパスや private の名前を書かない）。公開の写しでは、「計画レビューの記録」の生の出力と版の一時パス（ハーネスの一時ディレクトリの下で、ホストのユーザー名を `-home-<user>-` として含む）と session ID を「（非公開の場所に保存）」に置き換え、commit の前に `grep -nE 'home|/tmp/|session' docs/superpowers/plans/2026-11-12-home-mount.md docs/superpowers/specs/2026-11-12-home-mount-design.md` で、ホストのパスとユーザー名が残っていないことを目で確かめる（`/home/node` は c3c の公開の配置なので残ってよい）。生の出力の写しは公開の置き場に置かず、保守者の非公開の場所に置く。実装者はその commit の上から始める。

**実行の場所:** Task 1〜3 と Task 5 はホストの Claude で行う（Task 3 は実 podman が要る）。Task 4 はコンテナの中の確認なので、持ち主に `-b` でコンテナを起動してもらい、結果を受け取る。

## Global Constraints

**REQUIRED SUB-SKILL:** Use superpowers:test-driven-development（コードを変える計画。Task 1 の前に 1 回読み込む）

- 既定（両キーとも未指定・空）で、起動・`--check` の挙動と、compose に渡す引数・環境は変わらない。例外は `ASSET_HASH`: 2 つの override を `ASSET_HASH_TARGETS` に足すので値が変わり、既存のイメージには `-b` するまでドリフトの WARNING が出る（前例と同じく意図した挙動。`docs/development-invariants.md` の `node-version.txt` の項と同じ扱い）。
- 各キーは 1 つのディレクトリだけ。値は絶対パスか `~/` 始まり。`~` 単独・`~/`（HOME 自身）は拒否。
- 綴りの検査に加え、`cd -P` で解決した実体も、`cd -P` で解決したホストの `$HOME`（番兵付き、先頭の `//` を `/` に正規化。`guard_codex_host_plugins()` c3c:2189 と同じ）の配下（`$HOME` 自身を除く）で、実の相対パスが `.` で始まらないこと（spec「実体にも綴りと同じ条件を課す」）。
- destination は綴りから算出した `/home/node/<相対>`（symlink 未解決、末尾 `/` と `//` は `normalize_instruction_path` で正規化）。source は物理解決の実体。
- 実体の名前のコロン・制御文字（末尾の改行を含む）は拒否（#112 と同じ番兵の取り方）。
- ガードの冒頭で `C3C_HOME_MOUNT_SOURCE` `C3C_HOME_MOUNT_TARGET` `C3C_HOME_MOUNT_RO_SOURCE` `C3C_HOME_MOUNT_RO_TARGET` を `unset` し、検証後にだけ export する（環境からの注入を防ぐ）。
- 新しいガードは `guard_fail` / `guard_warn` だけで判定し、通常起動と `--check` の両方の dispatch に入れる（`docs/development-invariants.md` の guard の不変条件）。新しいガードのエラーと警告の文面には、必ずキー名（`HOME_MOUNT` か `HOME_MOUNT_RO`）を入れる（テストが別のガードの ERROR と区別するため）。重なりの警告は「重なる」を含む文にする（未知のキーの WARNING `…のキー HOME_MOUNT は c3c が解釈しないため無視します。` と区別するため）。
- 挙動を変える commit には README の該当節を同じ commit で含める（root `AGENTS.md`「開発の進め方」）。
- シェルを編集したらそのターンで `./lint.sh` を走らせ、rc 0・警告ゼロ。
- 日本語で書く（README「表記」節）。

## Review Focus

1. **symlink で守っている領域へ逃げる値**（`~/x -> ~/.ssh`、`~/x -> /`、`~/x -> ~/.claude`）は拒否される → Task 1 のテスト `symlink の実体が条件を外れる値を拒否する`。
2. **隠し項目でない場所に置いた秘密や設定**（`SECRETS_DIR=~/secrets/c3c`、symlink の `GITCONFIG_FILE`、`CLAUDE_CONFIG_DIR=~/cfg`、c3c の checkout が `~/tools/c3c`）を `HOME_MOUNT` が含むと止まる → Task 1 のテスト `HOME_MOUNT が守っている領域を含むと止まる`。
3. **2 つのキーの重なりが source だけ、または destination だけ**（symlink で片方だけ重なる組）でも止まる → Task 1 のテスト `HOME_MOUNT と HOME_MOUNT_RO の重なりを拒否する`。
4. **`SHARED_MOUNT_HOME_ALIAS` の `~` 側の別名とのマウント先の重なり**（`~/vault` と `~/vault/sub`）は止まる → Task 1 のテスト `共有別名とマウント先が重なると止まる`。
5. **環境から内部変数を注入した起動**（`C3C_HOME_MOUNT_TARGET=/etc` を環境に置き、キーは未指定）で override も変数も渡らない → Task 1 のテスト `内部変数の注入を捨てる`。

---

### Task 1: launcher のガード・compose override・README

**Files:**
- Create: `compose.home-mount.yml`, `compose.home-mount-ro.yml`
- Modify: `c3c`（`ENV_FILE_ALLOWED_KEYS` c3c:749、`COMPOSE_OVERRIDE_ARGS` の前のコメント c3c:54-59、新しいガード関数を `guard_agents_dir()` の後、dispatch の通常起動 c3c:3193-3211 と `--check` c3c:2796-2814 の `guard_codex_host_plugins` の直後・`guard_env_boundary_keys` の前、`guard_env_boundary_keys` のキー一覧 c3c:2255、`resolve_asset_source` の fixed の case c3c:2475、`ASSET_HASH_TARGETS` c3c:2506-2535）
- Modify: `test-build.sh`（新しい関数 `run_home_mount_launcher_tests()` を `run_instruction_mount_launcher_tests` の後に足し、`run_launcher_tests()`（test-build.sh:1021）から呼ぶ。隔離用コピーの一覧 test-build.sh:1975 に 2 ファイルを足す）
- Modify: `tests/test_container_paths.py`（`CONTAINER_SIDE` に 2 ファイル）、`tests/test_c3c_config.py`（`test_fixed_boundary_assets_cannot_be_overridden_from_the_new_layout` の名前の一覧 :450-452 に 2 ファイル）
- Modify: `README.md`（「環境変数」の表は Step 3、ほかは Step 5）、`docs/development-invariants.md`、`examples/c3c/env.example`（Step 5）

**Interfaces:**
- Produces: `guard_home_mounts()`（引数なし。成功で 0、`guard_fail` で非 0）。export する変数 `C3C_HOME_MOUNT_SOURCE`（実体）・`C3C_HOME_MOUNT_TARGET`（`/home/node/<相対>`）・`C3C_HOME_MOUNT_RO_SOURCE`・`C3C_HOME_MOUNT_RO_TARGET`。override は `compose.home-mount.yml`（source `${C3C_HOME_MOUNT_SOURCE:?launcher が export する}`、target `${C3C_HOME_MOUNT_TARGET:?launcher が export する}`、`read_only` なし）と `compose.home-mount-ro.yml`（RO の 2 変数、`read_only: true`）。どちらも `type: bind`・`bind.create_host_path: false`、`compose.shared-home.yml` と同じ形。`--check` の行は `[OK]   HOME_MOUNT: <source> -> <target> (rw)` と `[OK]   HOME_MOUNT_RO: <source> -> <target> (ro)`。
- Consumes: `normalize_instruction_path`（c3c:2064）、`instruction_paths_overlap`（c3c:2073。末尾 `/` を除いて渡す）、`resolve_claude_config_base()`（c3c:1783。`CLAUDE_CONFIG_BASE_REAL` を設定する。副作用はこの 2 つの変数だけ）、`CLAUDE_SHARED_HOME_PATH`（`guard_shared_home_alias()` の export）、解決済みの `AGENTS_DIR`・`CODEX_DIR`、`~` 展開済みの `SECRETS_DIR`・`GITCONFIG_FILE`、`RUN_DIR`（c3c:283）、`CC_STATE_DIR`。

- [ ] **Step 1: 失敗するテストを書く**（`run_home_mount_launcher_tests()`。`launcher_sandbox_init` / `run_launcher` / `run_launcher_check` / `check` / `snapshot_check_targets` の既存の形を使う。値は `.c3c/env` に書く）

  最初に fixture を作る: `$home/data/pair` `$home/data/guard` `$home/.ssh` `$home/.claude` `$home/a:b` `$home/secrets/c3c` `$home/dot` `$home/agents/sub` `$home/x/agents` `$home/cfg/.claude`（と `$home/cfg/.claude.json` に `{}`）`$home/vault/sub` `$home/d/g` `$root/outside`、ファイル `$home/dot/gitconfig`、symlink は各ケースに書く。

  異常系の判定は、起動が rc≠0・出力に `ERROR:` に続いてキー名（`*"ERROR:"*"HOME_MOUNT"*`。RO のケースは `HOME_MOUNT_RO`）・`$root/compose-env` が無い、`--check` も rc≠0 と出力に同じ文字列。キーは、明記したケースを除き `HOME_MOUNT` と `HOME_MOUNT_RO` の両方で回す。

  正常系:
  - `正常: HOME_MOUNT を /home/node の同じ位置に rw で渡す`: `HOME_MOUNT=~/data/pair` → rc 0、compose-env に `C3C_HOME_MOUNT_SOURCE=<real home>/data/pair` と `C3C_HOME_MOUNT_TARGET=/home/node/data/pair`、compose-args に `compose.home-mount.yml`、`compose.home-mount-ro.yml` は無い。
  - `正常: HOME_MOUNT_RO を ro で渡す`: `HOME_MOUNT_RO=~/data/guard` → RO の 2 変数と `compose.home-mount-ro.yml`。
  - `正常: 両方を並べて渡す`: `~/data/pair` と `~/data/guard` → 2 ファイルとも積まれる。
  - `正常: 末尾の / と // を正規化する`: `HOME_MOUNT=~/data//pair/` → target が `/home/node/data/pair`。
  - `正常: HOME の中を指す symlink は実体を source にし、綴りを target にする`: `$home/link -> $home/data/pair` で `HOME_MOUNT=~/link` → source `<real home>/data/pair`、target `/home/node/link`。
  - `正常: --check は両方を診断し対象を変えない`: rc 0、出力に `HOME_MOUNT:` と `(rw)`、`HOME_MOUNT_RO:` と `(ro)`、`/home/node/data/pair`、snapshot の前後が `cmp` で一致。
  - `既定: 未指定と空は何も渡さない`: 未指定と `HOME_MOUNT=` / `HOME_MOUNT_RO=` の空 → compose-args に 2 ファイルとも無く、compose-env に `C3C_HOME_MOUNT` で始まる行が無い。
  - `内部変数の注入を捨てる`: `run_launcher C3C_HOME_MOUNT_SOURCE=/ C3C_HOME_MOUNT_TARGET=/etc C3C_HOME_MOUNT_RO_SOURCE=/ C3C_HOME_MOUNT_RO_TARGET=/etc`（キーは未指定）→ compose-env に `C3C_HOME_MOUNT` で始まる行が無い、override も無い。
  - `-b でも build と run の両方に渡す`: `c3c claude -b` を直接呼ぶ既存の形（test-build.sh:2344-2351）で、`compose-args.1` と `compose-args.2` の両方に 2 つの override、`compose-env.1` と `compose-env.2` の両方に 4 変数がある。
  - `境界キーの一覧に出す`: 両キーを設定した起動の出力の `guard_env_boundary_keys` の一覧に、両キー名が出る。
  - `rw の別マウントと重なると警告して起動する`: `EXTRA_MOUNT=~/data`、`SHARED_MOUNT=~/data`（別名なし）、`CODEX_DIR=~/data/codex`（ディレクトリを作る）のそれぞれと `HOME_MOUNT=~/data/pair` → rc 0、出力に `WARNING:`・`HOME_MOUNT`・`重なる`。`HOME_MOUNT_RO=~/data/guard` でも同じ。
  - `HOME_MOUNT_RO は守っている領域と重なっても止めない`: `SECRETS_DIR=~/secrets/c3c` と `HOME_MOUNT_RO=~/secrets` → rc 0。

  異常系:
  - `不正な値を拒否する`: `~`、`~/`、`$home`、`$root/outside`、`rel/path`、`$home/a/../b`、`$home/missing`、`$home/.ssh`、`$home/.claude`、`$home/.local/state/c3c`（作る）、`$home/a:b`。
  - `symlink の実体が条件を外れる値を拒否する`: `$home/l-ssh -> $home/.ssh`、`$home/l-out -> $root/outside`、`$home/l-root -> /`、`$home/l-claude -> $home/.claude`、`$home/l-home -> $home`。
  - `実体の名前のコロンと制御文字を拒否する`: `$home/l-colon -> $home/a:b`、`$home/l-nl -> "$home/nl"$'\n'`（test-build.sh:2400-2412 と同じ作り方。改行を落とした同名のディレクトリも作る）。
  - `HOME_MOUNT が守っている領域を含むと止まる`（`HOME_MOUNT` だけ）: `SECRETS_DIR=~/secrets/c3c`+`HOME_MOUNT=~/secrets`、`GITCONFIG_FILE=~/dot/gitconfig`+`HOME_MOUNT=~/dot`、symlink の `GITCONFIG_FILE=~/gc-link`（`-> $home/dot/gitconfig`）+`HOME_MOUNT=~/dot`、`AGENTS_DIR=~/agents`+`HOME_MOUNT=~/agents/sub`（中にある側）、`AGENTS_DIR=~/x/agents`+`HOME_MOUNT=~/x`（含む側）、`CLAUDE_CONFIG_DIR=~/cfg`+`HOME_MOUNT=~/cfg`、c3c の一式（test-build.sh:1975 の一覧に新しい 2 ファイルを足したもの）を `$home/tools/c3c` にコピーし、`local SCRIPT_DIR="$home/tools/c3c"`（test-build.sh:1980 の形）でそこから起動して `HOME_MOUNT=~/tools`（RUN_DIR）。
  - `HOME_MOUNT と HOME_MOUNT_RO の重なりを拒否する`: 同じ値；rw `~/d` と ro `~/d/g`；ro `~/d` と rw `~/d/g`；destination だけ重なる組（ディレクトリ `$home/f` と symlink `$home/f/l -> $home/data/guard` を作り、rw `~/f`・ro `~/f/l`。source は `~/f` と `~/data/guard` で重ならず、destination は入れ子）；source だけ重なる組（`$home/s1 -> $home/data/pair`、`$home/s2 -> $home/data/pair` として rw `~/s1`・ro `~/s2`）。
  - `共有別名とマウント先が重なると止まる`: `SHARED_MOUNT=~/vault`+`SHARED_MOUNT_HOME_ALIAS=1` と `HOME_MOUNT=~/vault/sub`、`HOME_MOUNT_RO=~/vault`、逆向き（`SHARED_MOUNT=~/vault/sub` と `HOME_MOUNT=~/vault`）。

- [ ] **Step 2: 失敗を確かめる**
  Run: `TMPDIR=/tmp ./test-build.sh --launcher-only 2>&1 | tail -60`
  Expected: 正常系のうち変数・override を確かめる check、`--check` の `[OK]` の check、警告（`重なる`）の check、異常系のうち `ERROR:` とキー名を見る check が FAIL。`既定: 未指定と空は何も渡さない`・`内部変数の注入を捨てる`・`HOME_MOUNT_RO は守っている領域と重なっても止めない` は実装前でも PASS してよい。既存の check は PASS のまま。

- [ ] **Step 3: 実装する**
  - 2 つの override を作る（先頭のコメントは `compose.shared-home.yml` に倣い、`${VAR:?}` は保険で本体は launcher の unset と export にあることを書く）。
  - `guard_home_mounts()` を書く。処理の順:
    1. 4 変数を unset。
    2. 各キーについて、値が空なら飛ばす → `~/` を `$HOME/` に展開（`~` 単独と `~/` は拒否）→ `normalize_instruction_path` → 綴りが正規化した `$HOME` の配下（自身を除く）・相対が `.` で始まらない → `-d` → `cd -P` に番兵で実体 → 実体のコロン・制御文字 → 実 HOME の配下・自身でない・実の相対が `.` で始まらない → destination `/home/node/<綴りの相対>`。
    3. 両キーを解決した後に重なりの検査（spec「重なりの扱い」の全項）:
       - 2 つのキーの source どうしと destination どうしが重なれば `guard_fail`。
       - 各キーの destination が `CLAUDE_SHARED_HOME_PATH`（設定されていれば）と重なれば `guard_fail`。ホストの `$HOME` が `/home/node` のときは、`CLAUDE_SHARED_HOST_PATH` と plugin の別名の destination とも比べる。
       - `HOME_MOUNT` の source が守っている領域と重なれば `guard_fail`。比べる対象と実体の取り方: `resolve_claude_config_base` を呼び、rc 0 なら `$CLAUDE_CONFIG_BASE_REAL/.claude`（`.claude` が無くてもこの綴りで比べる。rc 0 以外なら比べない〈後の `prepare_claude_config_ro()` が起動を止める〉）；`SECRETS_DIR`（存在すれば `cd -P`）；`GITCONFIG_FILE`（`realpath -e` でファイル自身の symlink も解決した実体。`HOME_MOUNT` が含む側だけ）；`AGENTS_DIR`（解決済み）；`$HOME/.codex/plugins/cache`（存在すれば `cd -P`）；`RUN_DIR`；`CC_STATE_DIR`（存在すれば `cd -P`、無ければ綴り）。
       - 各キーの source が rw の source（`WORKING_DIR`・`EXTRA_MOUNT`・`SHARED_MOUNT`・`CODEX_DIR`。`HOME_MOUNT_RO` はさらに `$CLAUDE_CONFIG_BASE_REAL/.claude`）と重なれば `guard_warn`（`~/` を展開し、存在すれば `pwd -P` で実体にしてから比べる。`guard_agents_dir()` c3c:2150-2162 と同じ形）。
    4. すべて通ってから export と `COMPOSE_OVERRIDE_ARGS+=`、`--check` の `[OK]` 行。ホストの `$HOME` が `/home/node` のときも同じ規則で、destination と source の綴りが一致するだけ（別名を足さない）。
  - 許可リスト・境界キー一覧・dispatch 2 か所・`resolve_asset_source`・`ASSET_HASH_TARGETS`・c3c:54-59 のコメント・test-build.sh:1975・`CONTAINER_SIDE`・`tests/test_c3c_config.py` の固定アセットの一覧に足す。
  - README の「環境変数」の表に `HOME_MOUNT` と `HOME_MOUNT_RO` の 2 行を足す（`--launcher-only` の E7〈test-build.sh:1781〉が許可リストと表の一致を見るので、Step 4 の前に要る。表の行の文面は Step 5 で整える）。

- [ ] **Step 4: 通ることを確かめる**
  Run: `TMPDIR=/tmp ./test-build.sh --launcher-only 2>&1 | tail -60` と `./lint.sh`
  Expected: 全 check PASS、lint rc 0・警告ゼロ（lint の compose 検査は Task 2 で足す）。

- [ ] **Step 5: 文書を書く**
  - `README.md`: 「環境変数」の表（README:184-187 付近）に 2 行；「ホストの指示ファイルとスキルをコンテナ内で解決する」節（README:218〜）に使い方の小節（例は `HOME_MOUNT=~/work/shared-data` と `HOME_MOUNT_RO=~/work/shared-guard` のような一般の名前。ホストのユーザー名・並走の固有のパスを書かない）；`--check` の検査項目（README:172）；compose.yml の項（README:635）；境界キーの一覧（README:799）；「Copilot CLI を使う」節の見えないもの（README:592）；「セキュリティモデル」節の rw の追加マウントの記述（README:769）；「変更後の確認」節（README:880）に `run_home_mount_launcher_tests` と Task 3 のプローブ。書く事実: マウント先の親を podman が作るので `/home/node` 直下の新しいディレクトリには node が書けない見込み（Task 4 の実測で確かめて直す）；Codex の sandbox は `--ro-bind / /` なので読める；Copilot の起動口の sandbox からは作業ディレクトリでなければ見えない；`HOME_MOUNT_RO` の `:ro` は別の rw マウントから同じ実体が見えれば境界にならない（警告する）；HOME の外を指す symlink は使えない；`HOME_MOUNT` が守っている領域を含むと止まる。
  - `examples/c3c/env.example`: `SHARED_MOUNT` の例の後に、2 つのキーのコメントの例（`# HOME_MOUNT=~/work/shared-data`・`# HOME_MOUNT_RO=~/work/shared-guard`）と 1〜2 行の説明。
  - `docs/development-invariants.md`: override の一覧（:38）に 2 ファイルと `guard_home_mounts()`；#99 の節（:40）の後に `guard_home_mounts()` の不変条件（unset と export、実体にも綴りと同じ条件、`HOME_MOUNT` が守っている領域を含むと `guard_fail`、比べる基点は `resolve_claude_config_base()` に一本化、ro と rw の入れ子を拒否する理由〈rw 側から symlink に差し替えて保護を外せる〉）；`ASSET_HASH` が変わりドリフトの WARNING が出るのは意図した挙動であること。
  - Run: `./lint.sh` → rc 0・警告ゼロ。

- [ ] **Step 6: Commit**
  ```bash
  git add c3c compose.home-mount.yml compose.home-mount-ro.yml test-build.sh tests/test_container_paths.py tests/test_c3c_config.py README.md docs/development-invariants.md examples/c3c/env.example
  git commit -m "feat: HOME_MOUNT と HOME_MOUNT_RO で HOME 配下を ~ の同じ位置につなぐ (#259)"
  ```

### Task 2: lint の compose 検査

**Files:**
- Modify: `lint.sh`（単独 config lint.sh:236-241、全 override 同時の config lint.sh:288-291 とその件数の文面 lint.sh:146・156・159、`compose_merged_overrides_ok` lint.sh:154、`${VAR:?}` の組 lint.sh:297）
- Modify: `tests/test-lint-compose-checks.sh`（関数の抽出 :12、fixture :128-160、lint 本体の配線の検査 :165-171）

**Interfaces:**
- Consumes: Task 1 の 2 ファイルと 4 変数名。ダミーの target は `/home/node/lint-home-mount`（rw）と `/home/node/lint-home-mount-ro`（ro）。

- [ ] **Step 1: 失敗するテストを書く**（`tests/test-lint-compose-checks.sh`）: 短縮表記と long syntax の両方の fixture に、`/home/node/lint-home-mount`（rw。long syntax では `read_only` を付けない別の項目として書く。:148 のループには入れない）と `/home/node/lint-home-mount-ro`（ro）を足す。ケース:
  - `9 ファイル: 2 つの home-mount があれば合格`（rc 0）。
  - `9 ファイル: lint-home-mount-ro が無ければ失敗`、`9 ファイル: lint-home-mount が無ければ失敗`、`9 ファイル: lint-home-mount-ro が rw なら失敗`、`9 ファイル: lint-home-mount が ro なら失敗`（いずれも rc 1）。
  既存の「7 ファイル」の名前のケースは「9 ファイル」に直す。
- [ ] **Step 2: 失敗を確かめる**: Run `bash tests/test-lint-compose-checks.sh`。Expected: 「無ければ失敗」「rw なら失敗」「ro なら失敗」の 4 ケースが FAIL（今の checker は追加の mount を見ないので合格してしまう）。
- [ ] **Step 3: 実装する**: 単独 config に 2 本；全 override 同時の config に 2 ファイルと 4 変数（ダミーの source は `/tmp`）を足し、件数の文面を「9 ファイル」に；`compose_merged_overrides_ok` の `:ro` の一覧に `/home/node/lint-home-mount-ro` を足し、`/home/node/lint-home-mount` が bind で残り `read_only` が付かないことを確かめる（新しい関数を作るなら tests の :12 の `sed` の抽出にも足す）；`${VAR:?}` の検査は 4 変数すべてについて、その変数だけを欠いた config が失敗することを確かめる（1 ファイル 1 変数の組を、1 ファイル 2 変数に広げる）；`tests/test-lint-compose-checks.sh:165` の配線の検査（`awk` が探す `-f compose.agents.yml -f compose.codex-plugins.yml config); then` の行と、ok・FAIL の文面の「7 ファイル」）を、新しい全 override 同時の config の行に合わせる。
- [ ] **Step 4: 通ることを確かめる**: Run `bash tests/test-lint-compose-checks.sh && ./lint.sh`。Expected: PASS、lint rc 0・警告ゼロ。
- [ ] **Step 5: Commit**: `git add lint.sh tests/test-lint-compose-checks.sh && git commit -m "test: lint で HOME_MOUNT の override を検査する (#259)"`

### Task 3: 実 podman のプローブ（rw・ro・flock）

**Files:**
- Modify: `test-build.sh`（`SHARED_ALIAS_PROBE` の近く test-build.sh:463、実構成の検査 test-build.sh:572-587 の後）

- [ ] **Step 1: テストを書く**: 新しいプローブ `HOME_MOUNT_PROBE` と実構成の check を足す。source は CONTEXT（`$root`、`/workspace` に rw）の外の `mktemp -d` に置く（test-build.sh:588-590 の Codex キャッシュの前例）: `hm=$(mktemp -d)`（rw）と `hmro=$(mktemp -d)`（ro）に `seed` を置き、`C3C_HOME_MOUNT_SOURCE="$hm" C3C_HOME_MOUNT_TARGET=/home/node/hm-probe C3C_HOME_MOUNT_RO_SOURCE="$hmro" C3C_HOME_MOUNT_RO_TARGET=/home/node/hmro-probe` を与えて 2 つの override を積み、`run --rm -T --entrypoint bash`。
  - `HOME_MOUNT は書けて、ホストに残る`: コンテナで `/home/node/hm-probe/new` を作る → ホスト側に `$hm/new` がある。
  - `HOME_MOUNT_RO は読めて書けない`: コンテナで `cat` は seed、`touch`・`mv` 置換・`rm` が失敗（既存の `expect_ro`）→ ホスト側の seed が不変で新しいファイルが無い。
  - `ホストとコンテナの flock が排他になる`: 親シェルで `exec {lfd}>"$hm/l"; flock "$lfd"`（同期的に取得して保持）→ コンテナで `flock -n /home/node/hm-probe/l true` が rc 1 → 親で `flock -u "$lfd"; exec {lfd}>&-`（失敗の経路でも閉じる）→ もう一度コンテナで `flock -n … true` が rc 0。
  - 終わったら `$hm` と `$hmro` を消す。
- [ ] **Step 2: 走らせる**: Run `TMPDIR=/tmp ./test-build.sh --config-ro-only 2>&1 | tail -60`（実 podman のあるホスト。README:844 のモード。プローブがこのモードで走らなければ全体の `TMPDIR=/tmp ./test-build.sh`）。Expected: 新しい check が PASS。
- [ ] **Step 3: lint**: `./lint.sh` rc 0・警告ゼロ。README「変更後の確認」節の記述（Task 1 Step 5）が実際に走ったモードと合っているか確かめ、違えば直す。
- [ ] **Step 4: Commit**: `git add test-build.sh README.md && git commit -m "test: HOME_MOUNT の rw・ro・flock を実 podman で確かめる (#259)"`

### Task 4: コンテナの実機の受け入れ（CI に入れない）

保守者の self-host の `.c3c/env`（gitignore 済み）に、一時的に `HOME_MOUNT=~/c3c-hm-probe/rw` と `HOME_MOUNT_RO=~/c3c-hm-probe/ro` を書く（`/home/node` の下に 2 段にして、podman が作る中間のディレクトリ `/home/node/c3c-hm-probe` を確かめられるようにする。1 段の名前では新しい親が作られない）（実装者がホストで書き、終わったら元に戻す）。持ち主に `-b` で起動してもらい、コンテナの中で次を確かめて結果を受け取る。

- [ ] `/home/node/<相対>` に rw の側が見え、コンテナから書いたものがホストで見える。ro の側は `touch` が失敗する。
- [ ] podman が作った中間のディレクトリ `/home/node/c3c-hm-probe` の所有者と、node から書けるかを確かめる。README（Task 1 Step 5）の記述と違えば直して commit する（`docs: HOME_MOUNT の親ディレクトリの挙動を実測に合わせる (#259)`）。
- [ ] Copilot の起動口で `/workspace` を作業ディレクトリにして canary を 1 回走らせ、sandbox の中から rw・ro 両方の目印が読めない（README「変更後の確認」節の Copilot の受け入れと同じ起動の組）。**目印が読めたら（spec の失敗条件）、先へ進まずに持ち主に報告する。**
- [ ] 未指定に戻した起動と `--check` の出力が、ドリフトの WARNING の行を除いて `main` の c3c と同じ（同じイメージを使う）。
- [ ] 結果を PR 本文に書く。確かめられなかった項目は `not run` と理由。

### Task 5: 完了と PR

**REQUIRED SUB-SKILL:** Use superpowers:verification-before-completion → superpowers:finishing-a-development-branch

- [ ] `./lint.sh`、`TMPDIR=/tmp ./test-build.sh --launcher-only`、Task 3 のモードの結果をそろえる。
- [ ] 区分が境界なので、PR 前の二重レビュー（Claude: `claude-review` skill、Codex: `codex-review` skill の Sol）を行う。Copilot の並走（公開の経路、`--diff <base の SHA> --unpushed <base の SHA>`）も Sol の直後に起動する。
- [ ] **REQUIRED SUB-SKILL:** Use superpowers:receiving-code-review — レビュー結果を受け取り、採否を決め、Critical・Important を直して確認限定巡を終える。
- [ ] push は持ち主に確かめてから。PR を作り、両レビューの全文を PR コメントに、判定・未対応の Minor・Task 4 の結果・`not run` を本文に書く。
- [ ] PR 後の二重レビューとマージは、作成に関わっていない対話セッションに handover で渡す。
- [ ] マージの後、新しい opt-in のキーなので minor のタグを提案する（root `AGENTS.md`）。利用側（findsummits）への連絡は #259 にコメントする。

---

## 計画レビューの記録

- Self-Review: 仕様の網羅・仮置き・名前の一致・スキルの指定を確認。`run_launcher_tests()` の場所の書き違いと、AGENTS_DIR のテスト値の曖昧さを修正。
- 版: `plan-initial.md` （非公開の場所に保存）
- Claude（claude-opus-5-5。modelUsage に claude-fable-5-2 も出た、所要 518 秒）: 修正後に渡せる。生の出力（一時）（非公開の場所に保存）
  - C1 `CLAUDE_CONFIG_DIR` を `~` 展開せずに比べる → 採用（`resolve_claude_config_base()` を使う）
  - I1 destination どうしを比べていない → 採用（比較とテストを追加）
  - I2 symlink の `GITCONFIG_FILE` → 採用（`realpath -e`、テスト追加）
  - I3 `ASSET_HASH` が変わり「1 バイトも変わらない」と矛盾 → 採用（制約に例外、Task 4 の比較を直す、invariants に書く）
  - I4 README を別の commit にしている → 採用（Task 1 に統合）
  - I5 異常系の判定が `ERROR:` だけ・fixture 不足 → 採用（キー名で判定、fixture の一覧）
  - M1 TDD の指定の位置 → 採用 / M2 並走に `--unpushed` → 採用 / M3 spec の commit → 採用（Context） / M4 Step 2 の Expected → 採用 / M5 lint のテストの抽出と fixture → 採用 / M6 flock の同期と置き場 → 採用 / M7 RUN_DIR のテストのコピー → 採用 / M8 境界の値と警告の組 → 採用 / M9 実 HOME の正規化 → 採用 / M10 canary が読めたときの扱い → 採用 / M11 行番号 → 採用 / M12 推奨の理由 → 採用
- Codex（gpt-6.1-sol、所要 176 秒）: 修正後に渡せる。生の出力（一時）（非公開の場所に保存）
  - C1 `GITCONFIG_FILE` 自体の symlink → 採用（Claude I2 と同じ）
  - C2 Claude 設定の比較の基点 → 採用（Claude C1 と同じ）
  - I1 source だけ・destination だけの重なりのテストが無い → 採用（2 組を追加。`HOME=/home/node` の正常系はダミー podman の仮 HOME では作れないので、テストではなく Step 3 の規則として書く）
  - I2 flock の同期 → 採用（親シェルで FD を保持）
  - I3 README を同じ commit に、spec の commit → 採用
  - M1 スキルの指定の位置 → 採用 / M2 lint の赤テスト → 採用
  - 見なかったこと: Codex の sandbox では `./lint.sh` の compose が `no such file or directory` で rc 1（環境制約。実装者がホストで走らせる）
- 確認限定巡 1: Codex（C1, C2, I1, I2, I3、所要 21 秒）→ すべて直った、実装に渡せる。生の出力（一時）（非公開の場所に保存）
- 確認限定巡 1: Claude（C1, I1〜I5、所要 20 秒、`--resume`）→ すべて直った、実装に渡せる。生の出力（一時）（非公開の場所に保存）
- carbon（並走、正式外。承認の後に起動）: gemini-4-carbon、101.96 クレジット、1355 秒、修正後に渡せる（Critical 3・Important 5・Minor 3）。生の出力 （非公開の場所に保存）。送ったのは `plan-initial.md`（公開の経路、`-c bbd09b9`、`-D docs/superpowers/plans/2026-11-12-home-mount.md`）。Sol と材料が違った点: spec は未追跡で送る root に無い、グローバル `AGENTS.md` と `.claude/AGENTS.md` は名前だけ（表の 2 列は貼った）
  - C1 destination の重なり・C2 比べる対象の解決・I4 flock と置き場・I5 スキルの位置 → Sol と Claude の指摘と同じで反映済み
  - C3 README の表を Step 5 で書くと Step 4 の E7 が FAIL → 採用（表の 2 行を Step 3 に移した）
  - I2 lint のテストの配線の検査（:165）と抽出（:12）の更新漏れ → 採用（Task 2 Step 3）
  - I3 `-b` の build と run の両方の検査、`tests/test_c3c_config.py` の固定アセットの一覧 → 採用（Task 1）
  - M1 1 段の名前では新しい親が作られない → 採用（Task 4 を 2 段の名前に）/ M2 `examples/c3c/env.example` → 採用（Task 1 Step 5）/ M3 PR の close の指定 → 不採用（#259 は findsummits の依頼で、マージ後に #259 にコメントして閉じるかは持ち主が決める）
- 確認限定巡 2: Codex（carbon から採った C3・I2・I3、出所は carbon の出力の番号、所要 20 秒）→ すべて直った、実装に渡せる。生の出力 （非公開の場所に保存）

区分: 境界（新しい rw のマウントでコンテナの境界を広げ、`:ro` の保護と秘密の置き場との重なりを判定するセキュリティ境界の変更のため）
推奨実装: Opus（判定順の 1〜5 に当たらず c3c の既定は Sonnet だが、セキュリティ境界を含むので Opus を推す条件に当たる。Codex は c3c の Claude Code 面の計画なので既定ではない。実装はホストの Claude で行い、Task 4 のコンテナの中の確認は持ち主に起動を頼む）
