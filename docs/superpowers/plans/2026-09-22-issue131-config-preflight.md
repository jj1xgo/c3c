# #131 保護対象の型不一致を作成前に拒否する

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 起動前から存在する保護対象のsymlink・型不一致がある場合、先行する不足項目を作らずに起動を拒否する。
**Architecture:** `prepare_claude_config_ro()` の通常起動で、全12項目の非破壊な事前検査を終えてから既存の作成処理へ進む。既存作成ループの直前検査とnoclobberを残し、事前検査後の競合への防御を弱めない。
**Spec:** https://github.com/jj1xgo/c3c/issues/131 。base `2308c8f`。
**Tech Stack:** Bash、既存のfake-Podmanランチャーテスト。

## 設計・範囲

- 現行mainから関数を抽出して一時HOMEで再現済み。`.claude/.git`のみ通常ファイルにするとrc1になる前にhooks～output-stylesの8ディレクトリが増える。CHECK_MODE=1は無書込。
- 対象: `c3c`、`test-build.sh`、READMEの保護対象説明、不変条件の順序契約の補足、本計画。
- 対象外: #132のエラー文改良・mountpoint probe、gitfile対応、マウント構成変更。実HOMEや実tokenには触れない。
- 今回の契約は「起動前からの型不一致/symlinkがあるなら作成前に拒否」。作成途中のI/Oエラーや並行変更の全ロールバックは保証しない。全拒否経路で無書込という過剰な既存コメントは、この射程に正す。
- 型判定は既存同様: dirsは `-L` 拒否、`-d` 許可、存在する他型拒否、欠落許可。filesは `-L`拒否、`-f`許可、存在する他型拒否、欠落許可。dangling symlinkも拒否。
- `--check` の無書込・警告とfail-closedを維持する。

## Task 1: 回帰と最小修正

Files: c3c / test-build.sh / README.md / docs/development-invariants.md

- [ ] `run_config_ro_launcher_tests()` に隔離したfixtureで以下を足す。実物c3c・既存fake-Podman入口とsnapshot helperを再利用。既存A/C等のfixtureを汚さない。
  1. `.git` がgitfile、他の保護項目は欠落。
  2. `.git` がディレクトリへの有効symlink、他は欠落。
  3. `.git` がdangling symlink、他は欠落。
  4. ファイル配列末尾 `statusline.sh` がディレクトリ、先行項目は欠落。
  5. `statusline.sh` が有効/無効symlink（同じ小ループで確認）、先行項目は欠落。
  通常起動と--checkそれぞれ、非0、該当pathのERROR/FAIL、保護対象 `.claude` だけの前後snapshot同一（型/内容/link/属性）、compose runが呼ばれないことを検証。通常の読み取りによるatimeは比較対象外。snapshotは台帳等を含むHOME全体にせず、`.claude` 以下のfind属性出力と通常ファイルhashをNUL/sortで比較する。全ケースに作成ログ0行を追加。新fixture群はFの後に置き、ケースごとに初期化する。既存B/B2にも作成ログ0行を追加。既存の正常系A（欠落12項目作成）、A2（冪等）も維持。
- [ ] 追加テストを旧実装で実行し、通常起動のsnapshot不変が失敗することをログに残す（RED）。既存`--launcher-only`入口を使う。時間短縮用に関数だけ抽出する場合も最終の正式入口は省略しない。
- [ ] 型判定をファイルシステムを変更しない（判定とguard_failの呼び出しのみ）トップレベルhelper `validate_claude_config_ro_path(path, kind)`（kindはdir/file、引数2個）へ抽出。`path` と `kind` をlocalに取り、symlinkを先に拒否、既存dir/fileなら0、他型なら既存文言のguard_fail＋return1、欠落なら0。エラーの4文は既存の文字列を逐語移動し、1箇所だけにする。内部呼出のkindは固定dir/fileで、不正kindは内部エラーとしてreturn1。新しい外部入力は無い。
- [ ] `prepare_claude_config_ro` のcfg自身の既存処理ブロック直後、既存dirsループの直前に通常起動だけの事前検査を置く:
  ```bash
  if [[ ${CHECK_MODE:-0} -eq 0 ]]; then
    for name in "${CLAUDE_CONFIG_RO_DIRS[@]}"; do
      validate_claude_config_ro_path "$cfg/$name" dir || return 1
    done
    for name in "${CLAUDE_CONFIG_RO_FILES[@]}"; do
      validate_claude_config_ro_path "$cfg/$name" file || return 1
    done
  fi
  ```
  両配列の検査後にのみ子placeholderの作成へ進む。cfg自体が無い場合の作成は既存どおり（子の既存不整合は無い）。cfgがdirectoryへのsymlinkの既存挙動は今回変えない。
- [ ] 作成側の既存2ループで、先にhelperをもう一度呼び、既存の `-d`/`-f` ならcontinue、欠落なら既存のCHECK_MODE警告または作成へ進む。作成時再検査とnoclobberは維持。CHECK_MODEは事前検査を通らず、既存順で不足WARNを出して不正項目で拒否する。
- [ ] c3cの既存コメント「起動を拒否する経路ではホストに何も書かない」を「起動前から存在する保護対象の型不一致・symlinkは子placeholder作成前に拒否する。作成途中の失敗のロールバックは行わない」に訂正。台帳等の別の書込を保証に含めない。
- [ ] `docs/development-invariants.md` に、通常起動は12項目を全件検査してから作成・作成時再検査とnoclobberを撤去しない・途中失敗ロールバックは契約外、の1項目を追加。
- [ ] READMEの読み取り専用保護説明に「既存対象の型/symlinkは不足項目作成前に確認し不正なら作成せず停止」を1文追加。同じコミットに含める。コメントで作成失敗/競合の全無書込を保証しない。
- [ ] `./lint.sh` と `TMPDIR=/tmp ./test-build.sh --launcher-only` を実行。Expected: lint OK、全既存/新規テスト成功。README「変更後の確認」はprepare_claude_config_ro変更時も `./test-build.sh --config-ro-only` を要求するため、既存localhost/claude-testイメージを使って実行する（イメージ存在確認を先行）。実機リビルドはnot run（マウント/イメージ/entrypoint変更なし）。
- [ ] git diff --check、対象ファイルのみのdiffを確認。未コミットでhostへ返す。コミット/pushの許可は別途既存承認と照合する。

## Review Focus

1. dirsを検査し終えただけで作成開始し、files末尾の不正で副作用が出ないか（末尾file型不一致回帰）。
2. dangling symlinkを欠落として扱わないか（dir/file両方回帰）。
3. 既存作成ループを弱めて競合時の上書きが起きないか（noclobberを維持、既存テストと静的確認）。
4. CHECK_MODEは事前検査を意図的に通さず既存ループの判定とWARNを維持し、書込が起きないか（全fixtureのcheckもsnapshot比較）。
5. 正常初回/再実行の作成数と設定内容が変わらないか（既存A/A2）。

実行方法: executing-plans（単一タスク）。実装: Opus — `~/.claude` 配下の保護対象とホスト書込の順序に効くため。
