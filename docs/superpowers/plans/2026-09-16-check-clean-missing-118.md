# 削除済みプロジェクトのイメージ清掃 実装計画（#118）

> **実行エージェント向け:** `superpowers:executing-plans` を使い、このセッション内でタスク単位に実行する。ユーザー承認前の自動コミット・push は行わない。

**目的:** `--check` の残存イメージ診断と、対象を確認できる欠落パスだけに限定した `--clean-missing` を追加する。

**構成:** Bash launcher が引数・通常診断・ビルド情報の配線を担当し、ホスト専用 Python ヘルパーが Podman JSON とパス判定を扱う。既存 `--clean` の破壊操作は再利用しない。

**技術:** Bash、Python 3 標準ライブラリ、Podman、Compose、unittest。

**仕様:** [清掃設計](2026-09-16-check-clean-missing-118-design.md)。基準 commit: `b3917de`。

## 共通制約

- 日本語の文書・メッセージ。既存の機械可読トークンを維持する。
- 通常 `--check` は対象リポジトリ、台帳、`.build-context/`、イメージを変更しない。
- 新清掃は `rmi --no-prune <full-id>` だけを使い、強制削除・全体 prune・コンテナ削除を行わない。
- metadata schema は `1`。不明・不整合・検査不能は削除不可。
- 元パスのラベルには論理絶対パスを使い、symlink の綴りを保持する。
- 一般設定からの任意コード実行・任意コマンド注入経路を増やさない。
- 計画を Opus の読み取り専用レビューに通す。実装前の設計確認後に着手する。

## 変更するファイル

| ファイル | 責務 |
| --- | --- |
| `claude-container` | CLI 検査、診断集約、ビルドへの由来情報受け渡し |
| `project-images.py`（新規） | パスとイメージの検査、限定削除、診断結果 JSON |
| `compose.yml` / `Dockerfile.claude` | 最終イメージの由来ラベル |
| `tests/test_project_images.py`（新規） | ヘルパーと実 launcher の回帰試験 |
| `test-build.sh` | 新テストの CI 配線、既存ダミー Podman の JSON 対応 |
| `README.md` / `docs/development-invariants.md` | 契約、制約、検証方法 |

## Task 1: パスとイメージの読み取り専用診断

**インターフェース:** `project-images.py --ledger <file> [--project=<absolute-path> ...] [--clean-missing] [--result-file <file>]`。stdout は人向けの日本語報告、終了コードは 0/1/2（成功・診断/清掃失敗・引数エラー）。内部関数 `path_state(path)` は `directory` / `missing` / `unverifiable` を返す。`project_key(path)` は既存 Bash と同じキーを返す。`read_inventory()` は全 ID、現在名、ラベル、履歴を分離して返す。結果ファイルは launcher が /tmp に mktemp で用意したモード 600 の一時ファイルで、`{"paths": [{"path": "/absolute/path", "state": "directory"}]}` の形式。Python は文字列の型と絶対パスを検証し、launcher は JSON から NUL 区切りで directory のパスだけを抽出する。JSON を shell として評価しない。生成・読取・解析失敗は FAIL。

- [x] `tests/test_project_images.py` を作り、欠落を見分ける試験を先に書く。例えば次の assertion を実 filesystem の一時ディレクトリ上で検証する。

  ```python
  self.assertEqual(path_state(str(root / 'missing')), 'missing')
  (root / 'file').write_text('x')
  self.assertEqual(path_state(str(root / 'file')), 'unverifiable')
  (root / 'broken').symlink_to(root / 'absent')
  self.assertEqual(path_state(str(root / 'broken')), 'unverifiable')
  self.assertEqual(path_state(str(root / 'file' / 'child')), 'unverifiable')
  ```

- [x] `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_project_images.py` で未実装による失敗を確認する。
- [x] errno を保持する成分ごとの `lstat` / `stat` を実装する。権限拒否は非 root の実 filesystem 試験と `PermissionError` 注入を使い分け、root での偽の成功を避ける。キーの同等性は既存 Bash の `compute_project_name()` を抽出して空白・日本語・記号・symlink、U+212A、U+0130、非 UTF-8 バイト、ルートパスと比較する。ASCII だけの小文字化と `os.fsencode()` のハッシュを使う。
- [x] ダミー Podman を executable として一時 PATH に置き、JSON fixture と呼び出しログを持たせる。`subprocess.run([...], check=False, capture_output=True, text=True)` を使い、非 0、JSON 破損、必須フィールド不足を明示的な失敗にする。実 JSON の `Names` と `RepoTags` の差を fixture に反映する。
- [x] ラベルと台帳による候補分類を実装する。ラベル矛盾、旧名の履歴だけ、dangling、複数タグ、同一キーの複数パスは保留にする。既存パスの台帳外イメージも報告する。既存の asset-hash 等だけを持つ旧イメージも台帳との照合対象にする。明示パスの検査では、無関係な候補を混ぜない。
- [x] fixture に新旧のプロジェクトと無関係イメージを同時に入れ、期待する ID だけが報告されること、診断では `rmi` 等を一度も呼ばないことを試験する。同じテストコマンドを成功させる。
- [x] 生存パスの名前なし旧 final と、asset-hash だけの名前なし中間イメージは件数だけを表示し、個別 ID の WARN を増やさないことを試験する。欠落パスの名前なし候補は ID を報告する。

## Task 2: 明示された欠落パスの限定清掃

**インターフェース:** Task 1 の CLI に実動作の `--clean-missing` を実装する。Podman 呼び出しは `images`、`image inspect`、`ps --all --external`、`rmi --no-prune`、`image exists` に限定する。台帳は書き込み用に開かない。

- [x] 状態機械の Podman ダミーで、削除すると ID が消え、失敗時は残るようにする。次の外部契約を先に試験し、赤になることを確認する。

  ```python
  self.assertEqual(result.returncode, 0)
  self.assertIn(['rmi', '--no-prune', image_id], calls)
  self.assertEqual(ledger.read_bytes(), ledger_before)
  self.assertEqual(ledger.stat().st_mode, ledger_mode_before)
  ```

- [x] 削除前に inspect・パス・全コンテナ参照を再取得し、失敗時は対象に触れない。停止、実行、外部コンテナの各 fixture で `rmi` 不呼び出しを確認する。競合による `rmi` の rc 2、125 は失敗として台帳を維持する。
- [x] `rmi --no-prune` 後に ID の消失を確認する。通常の非 0 と消失確認の rc 1 を混同しない。dangling は候補報告だけとして、名前付きの対象削除成功と分ける。参照・別名で削除できない名前付きの対象は FAIL とする。
- [x] 台帳に書き込めない環境でも、読めれば清掃できることを確認する。読み取り失敗、symlink、通常ファイル以外は FAIL とする。清掃の成功・失敗・再実行・対象なしの全ケースで元台帳の内容とモードを保持する。
- [x] 削除失敗、消失確認失敗、台帳読み取り失敗、複数対象の部分失敗をテストする。対象外行・イメージ・コンテナ・親イメージを変更しない assertion を置く。初回清掃成功後の再実行が「対象イメージなし」で成功することを検証する。
- [x] Task 1 と同じテストコマンドで全ケースを成功させる。

## Task 3: launcher、ビルド情報、文書の統合

**インターフェース:** launcher 内部の `CLEAN_MISSING=0/1`。ビルドの `CC_PROJECT_METADATA` / `CC_PROJECT_PATH` / `CC_PROJECT_NAME` は確定値を export してから readonly にし、Compose に渡す。Dockerfile 最終部（CMD より後）は既定値が空の同名 ARG と単一命令の `claude-container.project-*` ラベルを持つ。ヘルパーは `RUN_DIR` の固定パスから `python3 -I` で起動する。

- [x] 実 launcher に対する引数組み合わせテストを先に書く。`--check --clean`、`--clean-missing` 単独、3 フラグ併用を引数エラーとし、Podman 呼び出しログが空のままになることを赤で確認する。
- [x] 引数検査を `clean_all` より前へ追加する。`run_check_mode()` からヘルパーを 1 回呼び、終了コードを論理和で集約する。通常診断は既存のプロジェクト検査も続ける。清掃モードは結果 JSON の directory を既存検査へ必ず渡し、それ以外はヘルパーの診断・終了コードを採用する。directory が後から消えた場合も既存検査で FAIL になることを試験する。通常モードの欠落案内も新オプションの役割を反映する。
- [x] 台帳が空でも inventory を実行する。台帳外のラベル付き旧パス、台帳を新パスへ更新済み、明示した旧 symlink パスの各ケースで意図した範囲だけを清掃する。
- [x] `test-build.sh` のダミー `images --all --format json` は有効な空配列を返す。`run_check_mode` 試験用 runner の固定コピー一覧（基準1283行）に新ヘルパーを追加する。ヘルパー不在時は通常 SKIP / 清掃 FAIL を検証する。新 Python テストを `run_launcher_tests()` から 1 回呼ぶ。snapshot を使って通常診断の台帳・対象・build context の不変を確認する。
- [x] ヘルパーの通常診断は images だけを呼ぶことを確認する。清掃用ダミーは ps の JSON と image inspect の JSON に対応し、既存 launcher のテンプレート指定によるラベル検査と区別する。
- [x] Compose / Dockerfile にラベルを配線する。明示 build と暗黙 run の両方で実 launcher の記録値を検証する。プロジェクト env が同名変数を設定しても上書きされないことを試験する。直接 Dockerfile ビルドの三つの空ラベルは誤警告しない。改行を含むパスでは三つとも空にし、引用符・バックスラッシュを含むパスは実ビルドで label round-trip を確認する。
- [x] README の使い方・`--check`・イメージ管理・検証方法を更新する。台帳保持、候補保留、ディスク回収量を保証しないこと、ホストパスのラベル、媒体の未マウントと並行操作の制約、終了コード 0/1/2 を記載する。不変条件に no-prune・非強制削除・ラベル整合と両ビルド経路の配線を追記する。Dockerfile の変更により既存イメージには drift WARN が出ることを記録する。
- [x] 以下を実行し、スキップ・環境失敗と成功を分けて記録する。

  ```bash
  ./lint.sh
  TMPDIR=/tmp ./test-build.sh --validator-only
  TMPDIR=/tmp ./test-build.sh --launcher-only
  bash examples/hooks/tests/test-block-pr-approve.sh
  ```

- [x] 隔離した Podman storage で、プロジェクト名に対応した小さいテストイメージを作る。`--all --external` の実 JSON、停止・実行・Buildah の参照保護、非強制削除と `--no-prune` の親保持を確認する。実 Compose の config で引数を確認し、本体 Dockerfile の最終ラベルを実ビルドで検証する。ユーザーの既存イメージを削除しない。
- [x] 実装差分を `claude-review` の読み取り専用 Opus レビューに渡す。Critical / Important を解消し、レビュー済みの差分、検証結果、未検証項目を揃えてコミット・PR 公開の確認へ進む。

## 完了条件

仕様の各保護条件に対応する試験があり、必須チェックと実 Podman 検証の結果が記録されていること。PR 作成前レビューを完了していること。ユーザー承認後のコミット・push・PR 作成では全文レビューを添付し、作成後の二重レビューへ進む。タグは自動作成せず、CLI 追加と `--check --clean` 拒否の互換性を踏まえた SemVer 判断を別途提示する。

## 実装・検証記録（2026-09-16）

基準 `b3917de` に対して実装。設計レビューで、台帳の常時保持、名前なし候補の件数表示、由来ラベルの最終単一命令化を確定した。コードレビューで rootfs コンテナの空 ImageID、台帳パスの CR 保全、診断失敗時の表示を修正した。空 ImageID は実 Podman で再現し、フィールド欠落と区別して対処した。

| 検証 | 結果 |
| --- | --- |
| `./lint.sh`（Compose を含む） | 成功、警告なし |
| `--validator-only` | PASS 82 / FAIL 0 |
| `--launcher-only` | PASS 237 / FAIL 0。新規 Python テスト42件を含む |
| 同梱 hook テスト | 全ケース成功 |
| 実 Compose config | 日本語・引用符・バックスラッシュ・ドル記号を含む由来引数を保持 |
| Podman 5.8.6 の隔離ストレージ | 最終ラベル部の実ビルド、停止・稼働・Buildah 参照保護、rootfs 共存、限定削除、消失確認、親と base 保持、台帳不変、再実行が成功 |
| 製品イメージ全体の再ビルド・対話起動 | `not run`: 実行時境界は変更しておらず、変更した最終 ARG / LABEL 命令を隔離した小さいイメージで実ビルド検証 |
| GitHub Actions | `not run`: PR 作成前。上記の必須チェックはホストで実行済み |

sandbox のローカルソケット制限・Podman 実行領域の読み取り専用制限による失敗は、ホストで再実行して成功を確認した。これらを製品のテスト成功として数えていない。

Opus のコードレビューと限定再レビューを実施。最終判定は **Yes**、Critical / Important はなし。未対応の Minor は、ヘルパーが結果ファイル生成前に失敗した場合、台帳の既存診断が清掃案内を重ねて表示する点。終了コードは非 0 で削除も成功扱いにならず、他の実在プロジェクトの診断を継続できるため、文言だけの調整は本変更では保留した。
