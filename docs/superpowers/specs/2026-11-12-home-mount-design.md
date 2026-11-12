# ホストの HOME 配下のディレクトリを、コンテナの `~` の同じ位置に rw でつなぐ（設計）

対象: [#259](https://github.com/jj1xgo/c3c/issues/259)

## 意図

利用側プロジェクト（findsummits）は、正式なレビュアーと並べて Copilot CLI 経由の別モデルにも同じレビューをさせる試行（並走）を、ホストで走らせている。v20.2.0・v20.3.0 で Copilot CLI を sandbox 付きでコンテナに入れられるようになったので、コンテナの Claude からも並走を起動したい。並走は月の予算の台帳（`flock` を取って追記する JSONL）・送る前の検査の記録・出力の置き場をホストのディレクトリに持つ。予算を二重に使わないよう、ホストとコンテナで**同じファイル**を共有したい。今ある opt-in のマウント（`EXTRA_MOUNT` = `/data`、`SHARED_MOUNT` = `/shared`、`AGENTS_DIR` は `:ro`）は、利用側で別の用途に使っている。

保守者は、並走に限らず「ホストと同じ場所に見えれば、規則や記録に書いたパスがそのまま開けるのに」と思う場面がよくある。ただし、ホストの絶対パス（`/home/<host user>/...`）をコンテナの中に増やしたくない（外に送るものに混じるのを避けたい）。そこで、**ホストの `$HOME` から見た相対位置を、コンテナの `~`（`/home/node`）から見て同じ位置に**つなぐ。`~/foo/bar` と書けば、ホストでもコンテナでも同じ実体を指す。

並走のデータの中には、外に送る前の確認に使うファイル（学習への利用の拒否を確かめた日付の記録、非公開のリポジトリ名の一覧の写し）もある。どちらもホストが書き、コンテナは読むだけである。これをコンテナから誤って書き換え・消去できると、止まるはずの送信が通るおそれがある。そこで、書けるキーと並べて**読むだけのキー**も用意し、利用側は確認に使うファイルを読むだけの側に分けて置く。

並走は試行で、終わる予定がある。この機能は並走専用にせず、並走をやめても残しておいて困らない汎用の opt-in にする。

## 目標

- `.c3c/env` の新しいキー `HOME_MOUNT`（名前は設計者の判断。下記）に、ホストの `$HOME` 配下のディレクトリを 1 つ書くと、その実体がコンテナの `/home/node/<HOME からの相対パス>` に **rw** でつながる。未指定・空は何もしない（既定）。
- 同じ規則で、読むだけのキー `HOME_MOUNT_RO` を足す（`:ro`）。2 つは独立に opt-in でき、両方を指定するときは source も destination も互いに重ならない（一致・包含を拒否する）。
- ホストの `$HOME` が `/home/node` のときは、マウント先とホストのパスが一致する（そのまま 1 本）。
- ホストとコンテナで、同じファイルに対する `flock` が互いに排他になる（実機で確かめる）。
- Copilot の起動口（`/usr/local/bin/copilot`）の sandbox の中のコマンドからは、このマウントが見えない（作業ディレクトリにしない限り。README「Copilot CLI を使う」節の `/home/node` の扱いと同じ）。実機で確かめる。
- 起動時と `--check` で、ほかの opt-in と同じく検証し、境界に関わるキーの一覧（`guard_env_boundary_keys()`）にも出す。

## 目標にしないこと

- ホストと同じ絶対パス（`/home/<host user>/...`）への別名。保守者の判断で作らない（上の意図）。
- 複数のディレクトリをつなぐこと。c3c は固定の compose override を積む作りで、数を可変にすると生成や監査の範囲が広がる。2 つ目が要る場面が出たら、そのとき考える。
- `/workspace` をホストのパスで見せること、`EXTRA_MOUNT` を複数にすること。
- 利用側（並走のスクリプト・規則・台帳の ID の綴り）の変更。c3c の範囲外で、利用側が行う。
- 読むだけの側の保護を、悪意のある回避（環境変数で読む場所をずらすなど）まで含めて保証すること。`:ro` はこの mount 経由の誤った書き換えを防ぐだけで、同じ実体が別の rw マウントからも見えれば書ける（その場合は警告する。下記）。
- `HOME_MOUNT`（rw）側の書き込みの保護。このマウントは `SHARED_MOUNT` の `/shared` と同じく、コンテナの中から全面的に書ける。守る相手は誤りで、悪意ではない（#259 の「残るリスク」）。

## 失敗とみなすこと（動いても失敗）

- 既定（未指定）の起動・`--check`・compose の設定が、少しでも変わる。
- マウント先が、コンテナの中の既存のものを隠す・重なる（`/home/node` 直下の `.` で始まる領域〈`.claude`・`.codex`・`.copilot`・`.config`・`.agents` など〉、`SHARED_MOUNT_HOME_ALIAS` の `~` 側の別名、`/home/node` 自身）。
- source が、`:ro` で守っている領域（`~/.claude` の 13 項目など）を rw で見せる経路になるのに、黙って通る。
- 不正な値（相対パス、`..`、コロン・制御文字、HOME 外、HOME 自身、存在しない、symlink の実体が条件を外れる）が通る。
- Copilot の sandbox の中から、このマウントの中身が読める（作業ディレクトリでないのに）。
- 環境から注入した値で、launcher が検証していない destination にマウントされる。

## 決まったこと（保守者の決定、2026-11-12）

- 並走専用でなく汎用の opt-in にする。
- つなぐ先は、ホストの絶対パスではなく、`~` から見て同じ位置（`/home/node/<相対>`）にする。
- rw でつなぐ。
- 送る前の確認に使うファイルのために、読むだけのキーも c3c に足す（利用側の `~/.agents` に置く案は採らない。設定のリポジトリにデータを混ぜないため）。

## 設計者の判断（保守者は未確認）

- **キー名**: `HOME_MOUNT`（rw）と `HOME_MOUNT_RO`（`:ro`）。`SHARED_MOUNT`・`EXTRA_MOUNT` と並ぶ名前にし、「HOME からの位置を保つ」ことを表す。
- **各キー 1 つだけ**: 上の「目標にしないこと」。
- **検証の作り**: `guard_shared_home_alias()` の `~` 側の別名と同じ規則を流用する。
  - `normalize_instruction_path` で綴りを検査し、ホストの `$HOME` 配下（`$HOME` 自身を除く）で存在するディレクトリに限る。
  - HOME からの相対パスが `.` で始まれば拒否する（設定・認証の領域）。
  - source は `cd -P` で物理解決し、番兵付きで実体を得て、実体の名前のコロン・制御文字を拒否する（#112）。
  - **実体にも綴りと同じ条件を課す**（`guard_shared_home_alias()` より厳しくする）。物理解決した実体も、物理解決したホストの `$HOME` の配下（`$HOME` 自身を除く）で、HOME からの相対パスが `.` で始まらないこと。下の重なりの比較も実体どうしで行う。`~/x -> ~/.ssh`・`~/x -> /` のような symlink で設定・認証の領域を見せる経路を塞ぐため。代わりに、HOME の外（別のディスクなど）へ向く symlink は拒否される（保守者の使い方は symlink でないことを確かめた。必要になったら見直す）。
  - destination（`/home/node/<相対>`）は symlink 未解決の綴りで算出する（`SHARED_MOUNT_HOME_ALIAS` と同じ）。
  - 関数の冒頭で launcher が export する変数を `unset` し、検証後の値だけを `export` する（環境からの注入を防ぐ。`docs/development-invariants.md` の #99 の節と同じ構成）。
- **重なりの扱い**:
  - destination が `SHARED_MOUNT_HOME_ALIAS` の `~` 側の別名と重なる（一致・包含）なら拒否する（`guard_fail`）。互いの内容を隠すため。
  - ホストの `$HOME` が `/home/node` でないとき、destination が `SHARED_MOUNT_HOME_ALIAS` のホスト絶対パス別名や plugin の別名（`/home/<host user>/...`）と重なることは無い（`/home/node` の外のため）。`$HOME` が `/home/node` のときは destination とそれらの別名の関係も比べ、重なれば拒否する。
  - `HOME_MOUNT` と `HOME_MOUNT_RO` の source どうし、destination どうしが重なれば拒否する（`guard_fail`）。入れ子の `:ro` を rw の中に重ねる形は、rw 側から symlink に差し替えて保護を外せるため採らない（README「ホストの Claude Code 設定の読み取り専用保護」の symlink の議論と同じ）。
  - `HOME_MOUNT_RO` の source が、ほかの rw の source（作業ディレクトリ・`EXTRA_MOUNT`・`SHARED_MOUNT`・`CODEX_DIR`・`~/.claude`）と重なるときは `guard_warn` にする（別の rw 経路から書けることを知らせる。`AGENTS_DIR` と同じ扱い）。
  - `HOME_MOUNT` の source が、ほかの rw の source（作業ディレクトリ・`EXTRA_MOUNT`・`SHARED_MOUNT`・`CODEX_DIR`）と重なるときは `guard_warn` に留める（`AGENTS_DIR` と同じ。利用者が意図している可能性が高い）。
  - `HOME_MOUNT`（rw）の source が、**`:ro` で守っているものか、ホストで実行・参照されるもの**を含むか、その中にあるときは `guard_fail` にする。新しいキーは最初から塞ぐ（既存の rw マウントは README「ホストの Claude Code 設定の読み取り専用保護」の限界 (1) のとおり警告に留めているが、それは変えない）。比べる対象（いずれも設定されていて解決できるものの実体）:
    - `~/.claude`（`CLAUDE_CONFIG_DIR` 基点）
    - `SECRETS_DIR`、`GITCONFIG_FILE`（ファイル。含む側だけを比べる）、`AGENTS_DIR`、`CODEX_HOST_PLUGINS` の source（`$HOME/.codex/plugins/cache`）
    - launcher と compose ファイルの置き場（`RUN_DIR`）
    - state directory（`~/.local/state/c3c`）
    - `HOME_MOUNT_RO` の source（上の項）
    `$HOME` 直下の `.` で始まる項目の拒否で多くは塞がるが、`SECRETS_DIR=~/secrets/c3c` のように隠し項目でない場所に置く構成や、`CLAUDE_CONFIG_DIR` を別に置く構成のために明示して比べる。
  - `HOME_MOUNT_RO` の source が上の守っているものと重なるときは比べない（読むだけで、すでにコンテナから読めるものを別の位置に見せるだけのため）。
- **配線**: 固定の override `compose.home-mount.yml`（rw）と `compose.home-mount-ro.yml`（`read_only: true`）を足し、`type: bind`・`create_host_path: false`・`${VAR:?}` で source と target を受ける（`compose.shared-home.yml` と同じ形。rw の側は `read_only` を付けない）。`COMPOSE_OVERRIDE_ARGS` に積む。
- **マウント先の親**: `/home/node/<相対>` の親ディレクトリが無いと podman が作る。`/home/node` 直下の新しいディレクトリは podman が root 所有で作り、node から書けない。これは `SHARED_MOUNT_HOME_ALIAS` の `~` 側の別名と同じ挙動で、そのまま受け入れる（マウントした実体の中は書ける）。builder は実機でこの挙動を確かめ、README に書く。
- **SemVer**: 新しい opt-in のキーで既定は変わらないので minor。実装の後にタグを提案する（root `AGENTS.md`）。

## builder に任せること

- 関数の名前・分け方（`guard_shared_home_alias()` と検査を共有するかどうか）。
- `--check` の `[OK]` 行の文面、エラーの文面。
- `lint.sh` の compose の検証（override 単独・全ファイル同時の config に、rw のこの bind が残ること、`${VAR:?}` の fail-closed）と、`test-build.sh --launcher-only` のテストの組み方。
- README（「環境変数」の表、「セキュリティモデル」節の rw の追加マウントの記述、「変更後の確認」節）、`docs/development-invariants.md` の該当節の更新。

## 確かめること（実機、CI に入れない）

- `HOME_MOUNT_RO` の実体が `/home/node/<相対>` に見え、コンテナから書けない（`touch` が失敗する）。ホストで書いた変更はコンテナから見える。
- `-b` で起動したコンテナで、`HOME_MOUNT` の実体が `/home/node/<相対>` に rw で見え、コンテナから書いたものがホストで見える。
- ホストとコンテナから同じファイルに `flock` を取ると、後から取った側が待つ（`flock -n` が失敗する）。
- Copilot の起動口で、`/workspace` か `/home/node/copilot-work` を作業ディレクトリにして canary を走らせ、sandbox の中から `HOME_MOUNT` の中の目印が読めない。
- 未指定のときに起動と `--check` の出力が変わらない。
