# 旧製品名 claude-container の識別子の改名 第 1 段 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新名（`C3C_*` の env キー、`~/.local/state/c3c`、`io.c3c.*` label、`~/.config/c3c/secrets`、`C3C_DIR`）を正にし、旧名は `WARNING` 付きで従来どおり動かし続ける（MINOR）。

**Architecture:** launcher（`c3c`）が旧 env キーを新キーへ解決して旧キーを unset し、compose がコンテナへ新旧両方の名前で新キーの値を渡す。コンテナ側の `entrypoint.sh` は新キー優先・旧キー fallback。state directory は通常起動でだけ `renameat2(RENAME_NOREPLACE)` で移し、`--check`・`--clean` は移さずに旧を読む。label は新旧両方を書き、読むときは新優先（由来 label は組単位）。

**Tech Stack:** bash（`c3c`・`entrypoint.sh`・`lint.sh`・`test-build.sh`）、Python 3（`project-images.py`・unittest）、Podman Compose YAML、Dockerfile。

**Spec:** `docs/superpowers/specs/2026-09-27-rename-legacy-identifiers-design.md`（第 1 段の節と「検証」節。第 2 段は本計画の範囲外）

## Global Constraints

- 区分は境界。`c3c`・`compose.yml`・`Dockerfile.claude`・`entrypoint.sh`・`lint.sh`・`project-images.py`・`git-askpass.sh` を変更する前に `docs/development-invariants.md` の該当節を読む（root `AGENTS.md`）。
- 各 Task の編集後、そのターン内で `./lint.sh` を実行し終了コード 0・警告ゼロを確認する。Compose 検証をスキップした場合は `not run` と理由を報告する。
- 挙動を変えたら README.md の該当節を同じコミットで更新する（root `AGENTS.md`）。Task 7 でまとめて書く README の節も、各 Task の挙動変更と矛盾する記述を残さない。
- 日本語で書く（コード識別子・コマンドは英語のまま）。コメントは周囲のコード程度の密度で、「なぜ」を書く。
- 第 1 段で **変えないもの**: `/etc/claude-container/*`、`git-askpass.sh`・`entrypoint.sh` の `SECRETS_MOUNT`（旧パス）、`.claude-container.d/` の互換読み取り、`.gitignore`、`CC_*` 変数、`_claude-auth-workspace` 接尾辞、upstream の帰属表示、過去の plans/specs。
- 利用者が書く `C3C_` 接頭辞のキーは `C3C_IPV6` と `C3C_NO_FIREWALL` の 2 つだけ。`C3C_*` を readonly にしない。
- 空文字の env 値は未設定と同じに扱う（`${VAR:-}`）。
- state の rename は `renameat2(..., RENAME_NOREPLACE)` だけ。GNU `mv`・コピー・事前確認だけの代用は禁止。
- `--check` は何も書き込まない。`--check`・`--clean`・`--clean <dir>` は state を移行しない。
- 由来 label は組単位で選び、新旧を混ぜない（`docs/development-invariants.md` の「不完全な由来ラベルを旧形式照合へフォールバックしない」）。
- コミットは Task ごと。メッセージの末尾に、そのセッションのハーネスが示す attribution 行を付ける。push と PR 作成は持ち主の確認後。

## Review Focus

- `-b` していない旧イメージを、`.c3c/env` を `C3C_NO_FIREWALL=1` に書き換えた利用者が新 launcher で起動する → ファイアウォールが無効になる（compose がコンテナ側の旧名にも新キーの値を渡す）。Task 1 の lint の compose 補間検査（C-1）が、実 `podman compose config` の出力でコンテナ側の新旧両方の名前に新キーの値が入ることを見る。E-R5 はホスト側で launcher が新キーを export することだけを見る（fake podman の環境は補間前）。Task 8 の実機確認が実コンテナを見る。
- シェルの起動ファイルで旧キーを export したまま、`.c3c/env` に新キーを書いた利用者 → 両方が空でないので `ERROR` で止まり、どちらを消すか案内される。Task 1 の E-R3。
- 旧 state が別ファイルシステムへの symlink・bind mount（マウントポイント）の利用者 → コピーされず、symlink ならリンク自体が移る。rename(2) が `EBUSY`（マウントポイント）・`EXDEV`・`EINVAL` 等で使えない場合は旧 state を使い続けて手動の移行を案内する（毎回 ERROR で止めない）。Task 4 の S-2・S-6・E-1。
- 2 つの端末で同時に `c3c` を起動した直後の初回移行 → 片方が移し、もう片方は同一性で成功扱い。承認記録は失われない。Task 4 の S-4。
- 旧 state だけがある機械で `c3c --check`（引数なし）→ 旧台帳の全プロジェクトを診断し、何も書かない・移さない。Task 4 の S-8。

---

### Task 1: env キーを `C3C_*` へ解決する（launcher・compose・lint）

**Files:**
- Modify: `c3c`（`ENV_FILE_ALLOWED_KEYS` 付近 700-735、`guard_ipv6()` 757-780、`guard_env_boundary_keys()` 2023-2031、通常起動の guard 列 2902-2918、`check_one_project()` の guard 列 2518-2534）
- Modify: `compose.yml:43-45`、`compose.ipv6.yml:1,10`
- Modify: `lint.sh:195`
- Modify: `README.md`「環境変数」節の表（E7 の一致のため。本文の詳しい説明は Task 7）
- Test: `test-build.sh`（`run_env_file_launcher_tests()` 1425- と IPv6 の launcher テスト 1620-1650・1931-1941・2032）

**Interfaces:**
- Produces: `guard_env_key_renames()`（引数なし。解決後は `C3C_NO_FIREWALL`・`C3C_IPV6` だけが export され、`CLAUDE_CONTAINER_NO_FIREWALL`・`CLAUDE_CONTAINER_IPV6` は unset。両方が空でなければ `guard_fail`）。
- Produces: compose の補間変数は新キーだけ（`${C3C_NO_FIREWALL:-}`）。コンテナ内の env には `C3C_NO_FIREWALL`・`CLAUDE_CONTAINER_NO_FIREWALL`・`C3C_IPV6`・`CLAUDE_CONTAINER_IPV6` が同じ値で入る。

- [ ] **Step 1: 失敗するテストを書く**

`test-build.sh` の `run_env_file_launcher_tests()` の E3 を新キーの期待へ書き換え、**E3b の check と `printf '%s\n' "$out" >> "$LOG_FILE"` の後**（E4 の直前）に次のブロックを足す（`$envf`・`run_launcher`・`check` は同関数の既存のもの）。E3 と E3b の間に入れると、E3b が E-R 側の `compose-env` を読んで壊れる。

```bash
  # E-R1〜R6: 旧製品名の env キー（CLAUDE_CONTAINER_*）の解決（改名 第 1 段）。
  # E-R1: 旧キーだけ → WARNING で改名を勧め、compose には新キーの値だけが渡る（旧キーは unset）
  printf 'CLAUDE_CONTAINER_NO_FIREWALL=1\n' > "$envf"
  run_launcher
  check "E-R1: 旧キーだけは WARNING 付きで有効（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] && printf '%s' \"\$0\" | grep -q 'WARNING:.*CLAUDE_CONTAINER_NO_FIREWALL.*C3C_NO_FIREWALL' \
      && grep -qxF 'C3C_NO_FIREWALL=1' '$root/compose-env' && ! grep -q '^CLAUDE_CONTAINER_NO_FIREWALL=' '$root/compose-env'" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"
  # E-R2: 新キーだけ → WARNING なし、compose に新キー
  printf 'C3C_NO_FIREWALL=1\n' > "$envf"
  run_launcher
  check "E-R2: 新キーだけは改名の WARNING なし（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] && ! printf '%s' \"\$0\" | grep -q 'CLAUDE_CONTAINER_NO_FIREWALL' && grep -qxF 'C3C_NO_FIREWALL=1' '$root/compose-env'" "$out"
  # （NO_FIREWALL=1 の警告文は、ファイルに実際に書かれたキー名だけを出す — Step 3。旧名を常に併記すると上の否定が成り立たない）
  check "E-R2: 新キーでも NO_FIREWALL=1 の WARNING が出る" \
    bash -c "printf '%s' \"\$0\" | grep -q 'WARNING:.*C3C_NO_FIREWALL=1.*無効化'" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"
  # E-R3: 新旧の両方（値が同じでも、ファイルとシェルに分かれていても）→ ERROR で compose へ進まない
  printf 'C3C_NO_FIREWALL=1\n' > "$envf"
  run_launcher CLAUDE_CONTAINER_NO_FIREWALL=1
  check "E-R3: ファイルの新キーとシェルの旧キーの併存は ERROR（rc=$rc）" \
    bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR:.*CLAUDE_CONTAINER_NO_FIREWALL.*C3C_NO_FIREWALL' && [ ! -e '$root/compose-env' ]" "$out"
  printf 'CLAUDE_CONTAINER_IPV6=1\nC3C_IPV6=1\n' > "$envf"
  run_launcher
  check "E-R3: 同じファイルの新旧併存も ERROR（rc=$rc）" \
    bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR:.*CLAUDE_CONTAINER_IPV6.*C3C_IPV6' && [ ! -e '$root/compose-env' ]" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"
  # E-R4: 空文字は未設定扱い（空の旧キーと新キーは併存にならない）
  printf 'CLAUDE_CONTAINER_NO_FIREWALL=\nC3C_NO_FIREWALL=1\n' > "$envf"
  run_launcher
  check "E-R4: 空の旧キーは未設定扱い（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] && grep -qxF 'C3C_NO_FIREWALL=1' '$root/compose-env'"
  # E-R5: env ファイルなしで、シェル環境の旧キーも解決される
  rm -f "$envf"
  run_launcher CLAUDE_CONTAINER_NO_FIREWALL=1
  check "E-R5: シェル環境の旧キーも新キーへ写る（rc=$rc）" \
    bash -c "[ $rc -eq 0 ] && grep -qxF 'C3C_NO_FIREWALL=1' '$root/compose-env' && ! grep -q '^CLAUDE_CONTAINER_NO_FIREWALL=' '$root/compose-env'"
  # E-R6: --check は旧キーを [WARN]、併存を [FAIL] に集計する（env ファイルなし・シェル環境でも）
  # （fixture に packages.txt 等が無く、check_one_project は常に WARN を立てるので、「結果: WARN」ではなく改名の警告行で判定する）
  run_launcher_check CLAUDE_CONTAINER_IPV6=0
  check "E-R6: --check は旧キーを改名の WARNING で示す（rc=$rc）" \
    bash -c "printf '%s' \"\$0\" | grep -q 'WARNING: CLAUDE_CONTAINER_IPV6 は旧名です。C3C_IPV6'" "$out"
  run_launcher_check CLAUDE_CONTAINER_IPV6=0 C3C_IPV6=0
  check "E-R6: --check は併存を FAIL（rc=$rc）" \
    bash -c "[ $rc -ne 0 ] && printf '%s' \"\$0\" | grep -q 'ERROR: CLAUDE_CONTAINER_IPV6 と C3C_IPV6 が両方' && printf '%s' \"\$0\" | grep -q '結果: FAIL'" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"
```

E3（許可キーが全て compose へ届く）の `printf` 2 行と期待 2 行を新キーに変える:

```bash
    printf 'C3C_NO_FIREWALL=1\n'
    printf 'C3C_IPV6=1\n'
...
      && grep -qxF 'C3C_NO_FIREWALL=1' '$root/compose-env' \
      && grep -qxF 'C3C_IPV6=1' '$root/compose-env' \
```

D1 の `.env` に書く値（`CLAUDE_CONTAINER_NO_FIREWALL=1`）は `.env` が無視されることの検査なので、`C3C_NO_FIREWALL=1` に変える。IPv6 の launcher テスト（1620-1650・1931-1941 付近）の `printf 'CLAUDE_CONTAINER_IPV6=%s\n'` と、2032 行目の `CLAUDE_CONTAINER_IPV6=1` は `C3C_IPV6` に変える（旧キー経路は E-R1〜R6 が見る）。`run_launcher_check` は引数を受け付けるよう既存定義どおり `"$@"` を渡している（`# shellcheck disable=SC2120` を維持）。

- [ ] **Step 2: 失敗を確認する**

Run: `./test-build.sh --launcher-only; grep -E '(E-R|E3).*\[FAIL\]' .claude/test-results/*.log | tail -20`（ログは説明の後ろに `[FAIL]` を出す）
Expected: E-R1〜E-R6 と書き換えた E3 が FAIL（`guard_env_key_renames` が無く、`C3C_*` は許可リスト外）。

- [ ] **Step 3: launcher を実装する**

`c3c` の `ENV_FILE_ALLOWED_KEYS` に新キーを足し、直上のコメントのキー例を更新する:

```bash
  TZ
  C3C_NO_FIREWALL
  C3C_IPV6
  CLAUDE_CONTAINER_NO_FIREWALL
  CLAUDE_CONTAINER_IPV6
```

`guard_legacy_vars()` の直後に追加する:

```bash
# 旧製品名の env キー（CLAUDE_CONTAINER_*）を新キー（C3C_*）へ解決する（改名 第 1 段。spec
# docs/superpowers/specs/2026-09-27-rename-legacy-identifiers-design.md）。旧キーは WARNING 付きで有効。
# 空文字は未設定と同じ扱い。新旧の両方が空でなければ、値が同じでも混ぜずに止める（.c3c/env と
# シェル環境のどちらから来たかは問わない）。解決後は旧キーを unset し、以降の launcher と compose の
# 補間は新キーだけを見る。compose は新キーの値をコンテナへ新旧両方の名前で渡すので、旧イメージの
# entrypoint.sh も従来どおり動く。C3C_* は readonly にしない（load_env_file の無条件 export と衝突する）。
guard_env_key_renames() {
  local _ekr_pair _ekr_old _ekr_new _ekr_rc=0
  for _ekr_pair in CLAUDE_CONTAINER_NO_FIREWALL:C3C_NO_FIREWALL CLAUDE_CONTAINER_IPV6:C3C_IPV6; do
    _ekr_old="${_ekr_pair%%:*}"
    _ekr_new="${_ekr_pair##*:}"
    if [[ -n "${!_ekr_old:-}" && -n "${!_ekr_new:-}" ]]; then
      guard_fail "ERROR: $_ekr_old と $_ekr_new が両方設定されています（値が同じでも混ぜません）。" \
        "旧キー $_ekr_old を .c3c/env とシェル環境から削除し、$_ekr_new だけを使ってください。" || _ekr_rc=1
      continue
    fi
    if [[ -n "${!_ekr_old:-}" ]]; then
      guard_warn "WARNING: $_ekr_old は旧名です。$_ekr_new に書き換えてください（旧名は次のメジャー版で使えなくなります。README「環境変数」節）。"
      export "$_ekr_new=${!_ekr_old}"
    fi
    unset "$_ekr_old"
  done
  return "$_ekr_rc"
}
```

通常起動の guard 列で `guard_legacy_vars` の次に `guard_env_key_renames` を、`check_one_project()` の列で `guard_legacy_vars || true` の次に `guard_env_key_renames || true` を足す。

`guard_ipv6()` の `CLAUDE_CONTAINER_IPV6` 4 か所を `C3C_IPV6` に変える（エラー文も新キー名）。label の読み取りは Task 5 で変える。

`guard_env_boundary_keys()` の NO_FIREWALL 検査を新旧両方の名前にし、警告文にはファイルに実際に書かれたキー名を出す:

```bash
  local nf_key
  # 実際に書かれたキー名を出す（新旧を常に併記すると、新キーだけの利用者にも旧名が表示される）。
  # -m 1 で最初の 1 行だけ（head へのパイプは SIGPIPE で偽になりうる）。不一致は rc 1 で if の偽。
  if nf_key=$(grep -m 1 -oE '^(C3C|CLAUDE_CONTAINER)_NO_FIREWALL=1[[:space:]]*$' "$ENV_FILE" 2>/dev/null); then
    guard_warn "WARNING: $ENV_FILE で ${nf_key%%=*}=1 が設定されています。エグレスファイアウォールは無効化されます。"
  fi
```

E-R2 の期待（`C3C_NO_FIREWALL=1.*無効化` があり、`CLAUDE_CONTAINER_NO_FIREWALL` が無い）はこの文言に合う。`c3c` 内のコメント（690・704 行目、2023 行目の説明）の旧キー名も新キー名に直す。

- [ ] **Step 4: compose と lint を変える**

`compose.yml` の environment:

```yaml
      # エグレス制限の無効化。ホスト側は新キー C3C_NO_FIREWALL だけから補間する（launcher が旧キーを
      # 新キーへ解決済み）。コンテナへは新旧両方の名前で同じ値を渡す — 改名 第 1 段では -b していない
      # 旧イメージの entrypoint.sh が旧名しか読まないため（第 2 段で旧名を外す）。
      C3C_NO_FIREWALL: ${C3C_NO_FIREWALL:-}
      CLAUDE_CONTAINER_NO_FIREWALL: ${C3C_NO_FIREWALL:-}
      # mode と sysctls/network の不一致を避ける。IPv6用overrideが固定値1へ変える（新旧両方の名前）。
      C3C_IPV6: "0"
      CLAUDE_CONTAINER_IPV6: "0"
```

`compose.ipv6.yml`: 1 行目のコメントを `# launcher が C3C_IPV6=1 のときだけ追加する固定設定。` にし、environment を次にする。

```yaml
    environment:
      C3C_IPV6: "1"
      CLAUDE_CONTAINER_IPV6: "1"
```

`lint.sh:195` の needle を新旧両方にする:

```bash
        "net\.ipv6\.conf\.all\.disable_ipv6: ${q}0${q}" "C3C_IPV6: ${q}1${q}" "CLAUDE_CONTAINER_IPV6: ${q}1${q}"; do
```

`compose.ipv6.yml` は境界アセット（`ASSET_HASH_TARGETS`）なので、既存イメージではドリフトの `WARNING` が出る（spec どおり）。

`lint.sh` の compose 検証（`podman compose -f compose.yml config` の行の直後）に、補間元の回帰検査 C-1 を足す（fake podman の環境は補間前なので、コンテナへ渡る値はここでしか自動検査できない）:

```bash
  # 改名 第 1 段（C-1）: コンテナ側の新旧両方の名前が、ホスト側の新キー C3C_NO_FIREWALL だけから補間されること。
  # 旧名側の補間元を旧キーに戻すと、.c3c/env を新キーへ書き換えた利用者の旧イメージで無効化が黙って効かなくなる。
  q="['\"]?"
  if nf_on=$(env -u CLAUDE_CONTAINER_NO_FIREWALL C3C_NO_FIREWALL=1 podman compose -f compose.yml config) \
      && nf_off=$(env -u C3C_NO_FIREWALL CLAUDE_CONTAINER_NO_FIREWALL=1 podman compose -f compose.yml config); then
    for key in C3C_NO_FIREWALL CLAUDE_CONTAINER_NO_FIREWALL; do
      grep -qE -- "^[[:space:]]*${key}: ${q}1${q}[[:space:]]*\$" <<<"$nf_on" \
        || { echo "ERROR: C3C_NO_FIREWALL=1 のとき compose のコンテナ側 $key が 1 になりません" >&2; status=1; }
      if grep -qE -- "^[[:space:]]*${key}: ${q}1${q}[[:space:]]*\$" <<<"$nf_off"; then
        echo "ERROR: compose のコンテナ側 $key がホスト側の旧キー CLAUDE_CONTAINER_NO_FIREWALL から補間されています" >&2; status=1
      fi
    done
  else
    status=1
  fi
```

（`q` は後段の IPv6 の needle でも同じ定義で使っている。重複定義で shellcheck が警告するなら、前段の定義をこのブロックの前へ移して 1 か所にする。）

- [ ] **Step 5: README の表を合わせる（E7）**

`README.md`「環境変数」節の表で、`CLAUDE_CONTAINER_IPV6` と `CLAUDE_CONTAINER_NO_FIREWALL` の行を `C3C_IPV6`・`C3C_NO_FIREWALL` に変え、その下に旧キーの行を足す:

```markdown
| `C3C_IPV6` | `0` | `1` で IPv4/IPv6 を併用し両方に許可リストを適用する。未指定・空・0は既存IPv4モード、その他は起動と `--check` で拒否。初回は対応イメージの `-b` が必要（後述） |
| `C3C_NO_FIREWALL` | (unset) | `1` でエグレス制限（後述）を無効化 |
| `CLAUDE_CONTAINER_IPV6` | — | `C3C_IPV6` の旧名。`WARNING` 付きで同じ意味に読む（次のメジャー版で廃止）。新名と同時に設定すると起動と `--check` で拒否 |
| `CLAUDE_CONTAINER_NO_FIREWALL` | — | `C3C_NO_FIREWALL` の旧名。扱いは上と同じ |
```

README の他の箇所の `CLAUDE_CONTAINER_NO_FIREWALL=1`・`CLAUDE_CONTAINER_IPV6=1` の用例は新キーに変える（`grep -n 'CLAUDE_CONTAINER_\(NO_FIREWALL\|IPV6\)' README.md` で確認。表の旧キーの行だけ残る）。`examples/c3c/env.example` に該当キーがあれば新キーに変える。

- [ ] **Step 6: テストを通す**

Run: `./lint.sh && ./test-build.sh --launcher-only`
Expected: `lint OK`、`--launcher-only` の FAIL 0（E7 を含む）。

- [ ] **Step 7: コミット**

```bash
git add c3c compose.yml compose.ipv6.yml lint.sh README.md test-build.sh examples/c3c/env.example
git commit -m "feat: env キー CLAUDE_CONTAINER_* を C3C_* へ解決する（旧キーは WARNING 付きで有効）"
```

---

### Task 2: `entrypoint.sh` が新キー優先・旧キー fallback で読む

**Files:**
- Modify: `entrypoint.sh:58-70`
- Test: `tests/test_ipv6_entrypoint.py`

**Interfaces:**
- Consumes: コンテナ env の `C3C_IPV6`・`C3C_NO_FIREWALL`（新 compose）または `CLAUDE_CONTAINER_*`（旧 compose＝ロールバック）。
- Produces: 抽出境界コメント（`BOUNDARY`）は変えない。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_ipv6_entrypoint.py` の `EntrypointTests` に追加する（既存テストの env は旧キーのまま残し、旧キー fallback の回帰とする）:

```python
    def run_first_half(self, env_extra):
        # 起動前半（BOUNDARY まで）だけを実行する。後半（秘密の export・ゲート・exec claude）へは進ませない
        # （test_refresh_loop_preserves_mode と同じ抽出。NO_FIREWALL=1 では sudo を通らないため、全体を実行すると
        # 後半の helper・/workspace・/dev/tty に触れうる）。
        full = (ROOT / 'entrypoint.sh').read_text()
        self.assertIn(BOUNDARY, full)
        source = full.split(BOUNDARY)[0]
        self.assertNotIn('\nexec claude', source)
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            fake = tmp / 'sudo'
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$RECORD"\nexit 1\n')
            fake.chmod(0o755)
            env = {'PATH': td + ':' + os.defpath, 'RECORD': str(tmp / 'record'), **env_extra}
            response = subprocess.run(['bash', '-c', source], env=env, text=True, capture_output=True,
                                      stdin=subprocess.DEVNULL, start_new_session=True, timeout=30)
            record = (tmp / 'record').read_text().splitlines() if (tmp / 'record').exists() else None
            return response, record

    def test_new_key_preferred_and_old_key_fallback(self):
        cases = [
            ({'C3C_IPV6': '1'}, ['--ipv6']),
            ({'CLAUDE_CONTAINER_IPV6': '1'}, ['--ipv6']),
            ({'C3C_IPV6': '1', 'CLAUDE_CONTAINER_IPV6': '1'}, ['--ipv6']),
            ({'C3C_IPV6': '', 'CLAUDE_CONTAINER_IPV6': '1'}, ['--ipv6']),
            ({'C3C_IPV6': '0', 'CLAUDE_CONTAINER_IPV6': '0'}, []),
        ]
        for env_extra, expected in cases:
            with self.subTest(env=env_extra):
                response, record = self.run_first_half(env_extra)
                self.assertEqual(response.returncode, 1)
                self.assertEqual(record, ['/usr/local/bin/init-firewall.sh', *expected])

    def test_conflicting_new_and_old_values_stop_before_firewall(self):
        for env_extra in ({'C3C_IPV6': '1', 'CLAUDE_CONTAINER_IPV6': '0'},
                          {'C3C_NO_FIREWALL': '1', 'CLAUDE_CONTAINER_NO_FIREWALL': '0'}):
            with self.subTest(env=env_extra):
                response, record = self.run_first_half(env_extra)
                self.assertEqual(response.returncode, 1)
                self.assertIsNone(record)
                self.assertIn('ERROR', response.stderr)

    def test_no_firewall_new_and_old_keys(self):
        for env_extra in ({'C3C_NO_FIREWALL': '1'}, {'CLAUDE_CONTAINER_NO_FIREWALL': '1'},
                          {'C3C_NO_FIREWALL': '1', 'CLAUDE_CONTAINER_NO_FIREWALL': '1'}):
            with self.subTest(env=env_extra):
                response, record = self.run_first_half(env_extra)
                self.assertEqual(response.returncode, 0, response.stderr)
                self.assertIsNone(record)
                self.assertIn('エグレスファイアウォールは無効です', response.stderr)
```

前半だけを実行するので、NO_FIREWALL=1 では sudo を呼ばずに BOUNDARY まで進み rc 0 で終わる（終了コードも検査できる）。

- [ ] **Step 2: 失敗を確認する**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_ipv6_entrypoint.py -v`
Expected: 新キーのケースと不一致のケースが FAIL。

- [ ] **Step 3: 実装する**

`entrypoint.sh` の 58-72 行（「# エグレス制限」のコメントから、`init-firewall.sh` 失敗時の `exit 1` を閉じる内側の `fi` まで）を次で置き換える。73 行目以降（監視ヘルパー `firewall-refresh.py` の起動と外側の `fi`）はそのまま残す:

```bash
# エグレス制限（deny-by-default 許可リスト）。失敗時は起動しない（fail-closed）。
# 無効化する場合は利用側プロジェクトの .c3c/env に C3C_NO_FIREWALL=1 を書く。
# 改名 第 1 段: 新キー（C3C_*）を優先し、未設定・空なら旧キー（CLAUDE_CONTAINER_*）を読む。旧 launcher の
# compose（旧キーだけを渡す）でこのイメージを起動したときも従来どおり効かせるため。新 compose は同じ値を
# 両方の名前で渡すので、値が食い違うのは想定外の経路 — firewall より前に止める。
c3c_resolve_mode_key() {
  local new_value="$1" old_value="$2" name="$3"
  if [ -n "$new_value" ] && [ -n "$old_value" ] && [ "$new_value" != "$old_value" ]; then
    echo "ERROR: $name と旧名の値が一致しません（$new_value / $old_value）。起動を中止します" >&2
    exit 1
  fi
  if [ -n "$new_value" ]; then printf '%s' "$new_value"; else printf '%s' "$old_value"; fi
}
C3C_IPV6_MODE=$(c3c_resolve_mode_key "${C3C_IPV6:-}" "${CLAUDE_CONTAINER_IPV6:-}" C3C_IPV6) || exit 1
C3C_NO_FIREWALL_MODE=$(c3c_resolve_mode_key "${C3C_NO_FIREWALL:-}" "${CLAUDE_CONTAINER_NO_FIREWALL:-}" C3C_NO_FIREWALL) || exit 1
firewall_args=()
case "${C3C_IPV6_MODE:-0}" in
  ''|0) ;;
  1) firewall_args+=(--ipv6) ;;
  *) echo "ERROR: C3C_IPV6 は0または1で指定してください。起動を中止します" >&2; exit 1 ;;
esac
if [ "$C3C_NO_FIREWALL_MODE" = "1" ]; then
  echo "WARNING: エグレスファイアウォールは無効です（C3C_NO_FIREWALL=1）。コンテナのネットワークは無制限です" >&2
else
  if ! sudo /usr/local/bin/init-firewall.sh "${firewall_args[@]}"; then
    echo "ERROR: ファイアウォールの設定に失敗しました。起動を中止します（無効化するには C3C_NO_FIREWALL=1）" >&2
    exit 1
  fi
```

コマンド置換の中の `exit 1` はサブシェルだけを終えるので、`|| exit 1` で親も止める（ERROR 文は stderr にそのまま出る）。その後の更新ループが `CLAUDE_CONTAINER_IPV6` を参照していれば（`grep -n CLAUDE_CONTAINER entrypoint.sh`）`C3C_IPV6_MODE` に変える。`entrypoint.sh` の他の `CLAUDE_CONTAINER_NO_FIREWALL` の言及（246 行目のコメント等）も新キー名にする。既存テスト `test_invalid_mode_rejected_before_sudo` の `assertIn('CLAUDE_CONTAINER_IPV6', ...)` は、新しいエラー文（`C3C_IPV6`）に合わせて `'C3C_IPV6'` に変える（入力は旧キーのままでよい — 旧キーの不正値も同じ検査に通ることの確認になる）。

- [ ] **Step 4: テストを通す**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*entrypoint*.py' -v && ./lint.sh`
Expected: 全 PASS、`lint OK`。

- [ ] **Step 5: コミット**

```bash
git add entrypoint.sh tests/test_ipv6_entrypoint.py
git commit -m "feat: entrypoint が C3C_* を優先し、未設定なら旧キーを読む"
```

---

### Task 3: compose の内部変数 `CLAUDE_CONTAINER_DIR` を `C3C_DIR` にする

**Files:**
- Modify: `c3c`（`CLAUDE_CONTAINER_DIR="$RUN_DIR"` の 4 か所: 695・1160・1391・1520 付近）、`compose.yml:6`、`.github/workflows/ci.yml:58`、`test-build.sh`（530-582・2149 付近）、`tests/test-runtime.sh:131`、`tests/test_c3c_launch.py`（fake podman の記録キーと `assert_run_dir`）、`tests/test_codex_launch.py`（同様の記録があれば）

**Interfaces:**
- Produces: compose の `dockerfile: ${C3C_DIR}/Dockerfile.claude`。互換は持たない（launcher と compose は同じ checkout で配られる）。

- [ ] **Step 1: テストを先に変える**

`tests/test_c3c_launch.py` の `PODMAN` の記録キー `'CLAUDE_CONTAINER_DIR'` を `'C3C_DIR'` に、`assert_run_dir` の `run['env']['CLAUDE_CONTAINER_DIR']` を `run['env']['C3C_DIR']` にする。`grep -rn CLAUDE_CONTAINER_DIR tests/ test-build.sh .github/` の残りも `C3C_DIR` にする。

- [ ] **Step 2: 失敗を確認する**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_c3c_launch.py -v 2>&1 | tail -5`
Expected: `EntryResolutionTests` が `KeyError`/不一致で FAIL。

- [ ] **Step 3: 実装する**

`c3c` の 4 か所の `CLAUDE_CONTAINER_DIR="$RUN_DIR"` を `C3C_DIR="$RUN_DIR"` に、`compose.yml` の `dockerfile: ${CLAUDE_CONTAINER_DIR}/Dockerfile.claude` を `dockerfile: ${C3C_DIR}/Dockerfile.claude` に、`.github/workflows/ci.yml` の `CLAUDE_CONTAINER_DIR: ${{ github.workspace }}` を `C3C_DIR: ${{ github.workspace }}` にする。`git grep -n CLAUDE_CONTAINER_DIR -- . ':!docs/superpowers'` が空になること（pathspec の除外は `git grep` で効く）（README・`docs/runtime-ci.md` の言及も直す）。

- [ ] **Step 4: テストを通す**

Run: `./lint.sh && ./test-build.sh --launcher-only`
Expected: `lint OK`（compose config が `C3C_DIR` 未設定でも既存どおり通るか、lint 側で与えている値を合わせる）、FAIL 0。

- [ ] **Step 5: コミット**

```bash
git add -u
git commit -m "refactor: compose の内部変数 CLAUDE_CONTAINER_DIR を C3C_DIR にする"
```

---

### Task 4: state directory を `~/.local/state/c3c` へ移す

**Files:**
- Modify: `c3c`（296-302 の `CC_STATE_DIR` 定義、`clean_all()` 313-335、`freeze_project_paths()` 464、`run_check_mode()` の冒頭 2700-2722）
- Create: `tests/test_state_migration.py`
- Modify: `tests/test_c3c_launch.py`（`self.state_dir` を新パスに。移行の launcher テストを追加）、`tests/test_project_images.py:97`（`self.ledger` を新パスに）、`test-build.sh`（`.local/state/claude-container` の全出現を `.local/state/c3c` に）、`tests/test_codex_launch.py`・`tests/test_claude_project_launch.py`（旧 state パスを使っていれば新パスに）

**Interfaces:**
- Produces（`c3c` のトップレベル、関数定義は `CC_STATE_DIR` の直前に置く）:
  - `rename_noreplace <src> <dst>`: rc 0=移動した、1=失敗（移動先が既にある `EEXIST` と、その他の想定外の errno）、3=この環境では上書きしない rename が使えない（python3 なし・`renameat2` なし・`EINVAL`/`ENOSYS`/`EOPNOTSUPP`（FS 非対応）・`EBUSY`（移動元がマウントポイント）・`EXDEV`）。rc 3 では旧 state を使い続ける。
  - `resolve_state_dir`: `CC_STATE_DIR`（実効の読み書き先）・`CC_LEGACY_STATE_DIR`・`CC_STATE_NOTICE`（`--check` で `[WARN]` に出す文。空なら出さない）を設定する。通常起動（`CHECK=0` かつ `CLEAN=0`）でだけ移行する。同一性の不一致では `exit 1`。
  - `CC_STATE_DIR`・`CC_LEGACY_STATE_DIR`・`CC_LEDGER_FILE` は `resolve_state_dir` の直後に readonly（`load_env_file()` より前。#39）。

- [ ] **Step 1: 関数単位の失敗するテストを書く**

`tests/test_state_migration.py` を作る。`c3c` から 2 関数を `sed` と同じ規則（`^name() {` から `^}` まで）で抽出し、bash で実行する。

```python
#!/usr/bin/env python3
"""state directory の自動移行（改名 第 1 段、spec の遷移表）の関数単位の回帰試験。

c3c から rename_noreplace() と resolve_state_dir() を抽出し、隔離 HOME で実行する。
rename の競合・失敗は rename_noreplace を差し替えて再現する。
"""
import ctypes
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]


def extract(name):
    text = (REPO / 'c3c').read_text()
    start = text.index(f'\n{name}() {{\n') + 1
    end = text.index('\n}\n', start) + 3
    return text[start:end]


class StateMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cc-state-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'home'
        self.base = self.home / '.local/state'
        self.base.mkdir(parents=True)
        self.old = self.base / 'claude-container'
        self.new = self.base / 'c3c'

    def run_resolve(self, check=0, clean=0, override=''):
        script = '\n'.join([extract('rename_noreplace'), override, extract('resolve_state_dir'),
                            'resolve_state_dir',
                            'printf "DIR=%s\\nNOTICE=%s\\n" "$CC_STATE_DIR" "$CC_STATE_NOTICE"'])
        env = {'HOME': str(self.home), 'PATH': os.environ['PATH'], 'CHECK': str(check), 'CLEAN': str(clean),
               'LC_ALL': 'C.UTF-8'}
        return subprocess.run(['bash', '-c', 'set -euo pipefail\n' + script], env=env, capture_output=True, text=True)

    def fields(self, result):
        return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)

    def skip_if_unsupported(self, result):
        # 実物の rename_noreplace が rc 3（RENAME_NOREPLACE 非対応の FS 等）なら旧 state を使い続ける。
        # その経路は S-6 が検査するので、実 rename を前提にするケースは skip にする。
        if self.fields(result).get('DIR') == str(self.old) and '安全に移行できない' in result.stderr:
            self.skipTest('この環境では RENAME_NOREPLACE が使えない')

    def make_old(self):
        (self.old / 'mcp-approvals').mkdir(parents=True)
        (self.old / 'projects').write_text('/p\n')
        return os.lstat(self.old)

    # S-1: 旧なし → 新、通知なし
    def test_no_old_uses_new_silently(self):
        r = self.run_resolve()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fields(r)['DIR'], str(self.new))
        self.assertEqual(r.stderr, '')

    # S-2: 旧ディレクトリだけ → 通常起動でエントリ自体が移り、inode も同じ
    def test_old_directory_is_renamed_on_normal_launch(self):
        st = self.make_old()
        r = self.run_resolve()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.skip_if_unsupported(r)
        self.assertFalse(os.path.lexists(self.old))
        self.assertEqual((os.lstat(self.new).st_dev, os.lstat(self.new).st_ino), (st.st_dev, st.st_ino))
        self.assertEqual((self.new / 'projects').read_text(), '/p\n')
        self.assertIn('WARNING', r.stderr)
        self.assertEqual(self.fields(r)['DIR'], str(self.new))

    # S-2b: 旧がディレクトリへの symlink → リンク自体が移り、指す先は変わらない
    def test_old_symlink_to_directory_moves_the_link(self):
        real = Path(self.temp.name) / 'elsewhere'
        real.mkdir()
        self.old.symlink_to(real)
        r = self.run_resolve()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.skip_if_unsupported(r)
        self.assertTrue(self.new.is_symlink())
        self.assertEqual(os.readlink(self.new), str(real))
        self.assertFalse(os.path.lexists(self.old))

    # S-3: 新旧の両方 → 新を使い、旧は残して WARNING
    def test_both_present_keeps_old_and_warns(self):
        self.make_old()
        self.new.mkdir()
        r = self.run_resolve()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.old.is_dir())
        self.assertEqual(self.fields(r)['DIR'], str(self.new))
        self.assertIn('旧版の c3c のセッションがすべて終わってから', r.stderr)

    # S-3b: 新が壊れた symlink でも「ある」扱い（上書きしない）
    def test_dangling_new_counts_as_present(self):
        self.make_old()
        self.new.symlink_to(self.base / 'nowhere')
        r = self.run_resolve()
        self.assertTrue(self.old.is_dir())
        self.assertTrue(self.new.is_symlink())
        self.assertEqual(self.fields(r)['DIR'], str(self.new))

    # S-4: rename 失敗後に新の同一性が一致（並行起動が先に移した）→ 成功扱い
    def test_concurrent_move_is_accepted_by_identity(self):
        self.make_old()
        override = 'rename_noreplace() { mv -T -- "$1" "$2"; return 1; }'
        r = self.run_resolve(override=override)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fields(r)['DIR'], str(self.new))

    # S-5: rename 失敗後に新が別物・無い → ERROR で止まる（黙って空にしない）
    def test_failed_move_with_different_target_stops(self):
        self.make_old()
        for override in ('rename_noreplace() { mkdir -p -- "$2"; return 1; }', 'rename_noreplace() { return 1; }'):
            with self.subTest(override=override):
                if self.new.exists():
                    self.new.rmdir()
                r = self.run_resolve(override=override)
                self.assertEqual(r.returncode, 1)
                self.assertIn('ERROR', r.stderr)
                self.assertTrue(self.old.is_dir())

    # S-6: 上書きしない rename が使えない → 旧 state を使い続け、新を作らない
    def test_unsupported_rename_keeps_using_old(self):
        self.make_old()
        r = self.run_resolve(override='rename_noreplace() { return 3; }')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.fields(r)['DIR'], str(self.old))
        self.assertFalse(os.path.lexists(self.new))
        self.assertIn('mv ', r.stderr)

    # S-7: 旧がファイル・壊れた symlink → 移さず新を使い、WARNING
    def test_unusable_old_is_not_moved(self):
        for make in (lambda: self.old.write_text('x'), lambda: self.old.symlink_to(self.base / 'nowhere')):
            with self.subTest():
                if os.path.lexists(self.old):
                    self.old.unlink()
                make()
                r = self.run_resolve()
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(os.path.lexists(self.old))
                self.assertFalse(os.path.lexists(self.new))
                self.assertEqual(self.fields(r)['DIR'], str(self.new))
                self.assertIn('WARNING', r.stderr)

    # S-8: --check・--clean は移さず、新が無ければ旧を読む。--check は stderr に出さず NOTICE に積む
    def test_check_and_clean_do_not_migrate(self):
        self.make_old()
        for check, clean in ((1, 0), (0, 1)):
            with self.subTest(check=check, clean=clean):
                r = self.run_resolve(check=check, clean=clean)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(self.old.is_dir())
                self.assertFalse(os.path.lexists(self.new))
                self.assertEqual(self.fields(r)['DIR'], str(self.old))
                if check:
                    self.assertEqual(r.stderr, '')
                    self.assertIn('次の通常起動で', self.fields(r)['NOTICE'])

    # 実物の rename_noreplace: 移動先が空ディレクトリでも上書きしない（通常の rename(2) は空ディレクトリを
    # 置き換えるので、NOREPLACE を外すとここで赤になる）。双方の inode が保たれること。
    def test_real_rename_noreplace_never_overwrites_empty_directory(self):
        old_st = self.make_old()
        self.new.mkdir()
        new_st = os.lstat(self.new)
        script = extract('rename_noreplace') + f'\nrename_noreplace "{self.old}" "{self.new}"'
        r = subprocess.run(['bash', '-c', script], env={'PATH': os.environ['PATH']}, capture_output=True, text=True)
        if r.returncode == 3:
            self.skipTest('この環境では RENAME_NOREPLACE が使えない')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(os.lstat(self.old).st_ino, old_st.st_ino)
        self.assertEqual(os.lstat(self.new).st_ino, new_st.st_ino)
        self.assertEqual(list(self.new.iterdir()), [])

    # errno の対応（E-1）: rename_noreplace の heredoc の Python を、renameat2 を偽物にして実行する。
    def run_helper_with_errno(self, err):
        text = extract('rename_noreplace')
        code = text.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]

        class FakeLibc:
            def renameat2(self, *args):
                ctypes.set_errno(err)
                return -1

        with mock.patch.object(ctypes, 'CDLL', lambda *a, **k: FakeLibc()), \
                mock.patch.object(sys, 'argv', ['-', 'src', 'dst']):
            with self.assertRaises(SystemExit) as caught:
                exec(compile(code, 'rename_noreplace', 'exec'), {'__name__': '__main__'})
        return caught.exception.code

    def test_errno_mapping(self):
        for err in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, errno.EBUSY, errno.EXDEV):
            with self.subTest(errno=errno.errorcode[err]):
                self.assertEqual(self.run_helper_with_errno(err), 3)
        for err in (errno.EEXIST, errno.ENOTEMPTY, errno.EACCES, errno.ENOENT):
            with self.subTest(errno=errno.errorcode[err]):
                self.assertEqual(self.run_helper_with_errno(err), 1)

    def test_real_rename_noreplace_moves(self):
        st = self.make_old()
        script = extract('rename_noreplace') + f'\nrename_noreplace "{self.old}" "{self.new}"'
        r = subprocess.run(['bash', '-c', script], env={'PATH': os.environ['PATH']}, capture_output=True, text=True)
        if r.returncode == 3:
            self.skipTest('この環境では RENAME_NOREPLACE が使えない')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.lstat(self.new).st_ino, st.st_ino)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 失敗を確認する**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_state_migration.py -v`
Expected: `extract` が `ValueError`（関数が無い）で全 FAIL/ERROR。

- [ ] **Step 3: 関数を実装する**

`c3c` の 296-302（`CC_STATE_DIR` の定義と readonly）を次で置き換える:

```bash
# 上書きしない rename（renameat2 の RENAME_NOREPLACE）。state directory の移行専用。
# GNU mv は別 FS（EXDEV）でコピーと削除へ切り替わり、事前の存在確認は確認と rename の間に現れた移動先を
# 上書きしうるので、どちらも使わない。rc 0=移動、1=失敗（移動先あり等）、3=この環境では使えない
# （python3 なし・renameat2 なし・FS 非対応・移動元がマウントポイント〈EBUSY〉・EXDEV）。rc 3 は旧 state を
# 使い続ける扱いなので、毎回の起動を止めない。symlink はリンク自体を移す（rename(2) の意味どおり）。
rename_noreplace() {
  command -v python3 >/dev/null 2>&1 || return 3
  python3 -I - "$1" "$2" <<'PY'
import ctypes, errno, os, sys
libc = ctypes.CDLL(None, use_errno=True)
try:
    renameat2 = libc.renameat2
except AttributeError:
    sys.exit(3)
AT_FDCWD, RENAME_NOREPLACE = -100, 1
src, dst = (os.fsencode(arg) for arg in sys.argv[1:3])
if renameat2(AT_FDCWD, src, AT_FDCWD, dst, RENAME_NOREPLACE) == 0:
    sys.exit(0)
sys.exit(3 if ctypes.get_errno() in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, errno.EBUSY, errno.EXDEV) else 1)
PY
}

# state directory（起動台帳・MCP/Codex/project 設定の承認記録・CLI 選択の記憶）を旧名
# ~/.local/state/claude-container から ~/.local/state/c3c へ移す（改名 第 1 段。spec の遷移表）。
# 判定は lstat（symlink を辿らない）。移行は通常起動でだけ行う — --check は書かず、--clean は選択記憶を
# 「読まない・書かない・消さない」不変条件を持つため state 全体を動かさない。両モードとも新が無ければ旧を読む。
# $HOME から直接算出して readonly にし、プロジェクト側 env からの上書きを封じる（#39）。
# ここは関数定義セクションより前なので guard_warn は使えない（stderr へ直接出す）。
resolve_state_dir() {
  local new="$HOME/.local/state/c3c" old="$HOME/.local/state/claude-container" before after rc=0
  CC_LEGACY_STATE_DIR="$old"
  CC_STATE_DIR="$new"
  CC_STATE_NOTICE=""
  local notice_both="旧 state $old が残っています（$new を使います）。旧版の c3c のセッションがすべて終わってから、中身を確認して削除してください。"
  if [[ ! -e "$old" && ! -L "$old" ]]; then
    return 0
  fi
  if [[ -e "$new" || -L "$new" ]]; then
    CC_STATE_NOTICE="$notice_both"
  elif [[ ! -d "$old" ]]; then
    CC_STATE_NOTICE="旧 state $old はディレクトリではないため移行しません（$new を使います）。不要なら削除してください。"
  elif [[ $CHECK -eq 1 || $CLEAN -eq 1 ]]; then
    CC_STATE_DIR="$old"
    CC_STATE_NOTICE="旧 state $old を読みます。次の通常起動で $new へ移行します。"
  else
    if ! before=$(stat -c '%d:%i' -- "$old"); then
      echo "ERROR: 旧 state $old の状態を確認できません。起動を中止します。" >&2
      exit 1
    fi
    rename_noreplace "$old" "$new" || rc=$?
    if [[ $rc -eq 0 ]]; then
      CC_STATE_NOTICE="state を $old から $new へ移行しました（承認記録・起動台帳・CLI の記憶を引き継いでいます）。"
    elif [[ $rc -eq 3 ]]; then
      CC_STATE_DIR="$old"
      CC_STATE_NOTICE="この環境では state を安全に移行できないため（python3 と上書きしない rename の対応が必要。$old がマウントポイントの場合も移せません）、旧 state $old を使います。c3c のセッションがすべて終わってから mv '$old' '$new' で移してください。"
    else
      after=$(stat -c '%d:%i' -- "$new" 2>/dev/null || true)
      if [[ "$after" != "$before" ]]; then
        echo "ERROR: state を $old から $new へ移行できませんでした。承認記録を失わないよう起動を中止します。$new の中身を確認し、手で移してから再実行してください。" >&2
        exit 1
      fi
    fi
  fi
  if [[ -n "$CC_STATE_NOTICE" && $CHECK -ne 1 ]]; then
    echo "WARNING: $CC_STATE_NOTICE" >&2
  fi
  return 0
}
resolve_state_dir
CC_LEDGER_FILE="$CC_STATE_DIR/projects"
readonly CC_STATE_DIR CC_LEGACY_STATE_DIR CC_STATE_NOTICE CC_LEDGER_FILE
```

`stat -c '%d:%i'`（`-L` なし）は lstat の値。`CHECK`・`CLEAN` は引数解析（この位置より前）で確定した 0/1。readonly ではないが、env の許可リスト外なので `.c3c/env` から変えられず、`load_env_file()` はこの後に走る。

- [ ] **Step 4: state を使う箇所を揃える**

- `freeze_project_paths()` の `MCP_APPROVAL_STORE="$HOME/.local/state/claude-container/mcp-approvals"` を `MCP_APPROVAL_STORE="$CC_STATE_DIR/mcp-approvals"` にする。
- `clean_all()` の `local approval_store=...` を実効の store にし、旧 state が別に残っていれば旧の承認記録と台帳も消す（選択記憶は新旧とも消さない）:

```bash
  local approval_store="$CC_STATE_DIR/mcp-approvals" legacy_store="$CC_LEGACY_STATE_DIR/mcp-approvals"
  echo "MCP 承認記録を削除します: $approval_store"
  rm -rf "$approval_store" && echo "削除しました。" || echo "見つからないのでスキップします。"
  echo "起動台帳を削除します: $CC_LEDGER_FILE"
  rm -f "$CC_LEDGER_FILE" && echo "削除しました。" || echo "見つからないのでスキップします。"
  # 旧 state（改名 第 1 段）が実効の state と別に残っていれば、承認記録と台帳だけを消す（選択記憶は消さない）。
  # 旧がディレクトリへの symlink でも対象にする（spec が引き継ぎ対象にしている配置。消すのはその中の
  # mcp-approvals と projects だけで、rm -rf は末尾の要素が symlink ならリンク自体を消し、その先を辿らない）。
  if [[ "$CC_LEGACY_STATE_DIR" != "$CC_STATE_DIR" && -d "$CC_LEGACY_STATE_DIR" ]]; then
    echo "旧 state の MCP 承認記録と起動台帳を削除します: $CC_LEGACY_STATE_DIR"
    rm -rf "$legacy_store" "$CC_LEGACY_STATE_DIR/projects"
  fi
```

- `run_check_mode()` の先頭（`umask 077` の直後）で通知を出す:

```bash
  if [[ -n "$CC_STATE_NOTICE" ]]; then
    echo "[WARN] $CC_STATE_NOTICE"
  fi
```

この `[WARN]` はプロジェクト単位の集計（サマリの WARN 数）と終了コードには入れない。state はプロジェクトに属さず、既存の集計はプロジェクトごとの結果だけを数えるため（spec の「`[WARN]` で出す」の範囲）。

- `c3c` に残る `.local/state/claude-container` を `grep -n 'local/state/claude-container' c3c` で確認し、`resolve_state_dir` 以外に無いこと。`agent-preference.py` は `$CC_STATE_DIR` を受け取るので変更しない。

- [ ] **Step 5: 既存テストの state パスを新パスにし、launcher テストを足す**

- `tests/test_c3c_launch.py`: `self.state_dir = self.home / '.local/state/c3c'`。`tests/test_project_images.py:97`: `self.ledger = self.home / '.local/state/c3c/projects'`。`test-build.sh`・他の `tests/*.py` の `.local/state/claude-container` を `.local/state/c3c` にする（`grep -rn 'local/state/claude-container' tests test-build.sh` が空になること。下の新規テストを除く）。
- `tests/test_c3c_launch.py` に追加する（`LaunchCase` のヘルパーを使う）:

```python
class StateMigrationLaunchTests(LaunchCase):
    """改名 第 1 段: 通常起動でだけ旧 state を移し、--check・--clean は移さず旧を読む。"""

    def make_legacy_state(self, agent='codex'):
        legacy = self.home / '.local/state/claude-container'
        pref = legacy / 'agent-preferences' / (self.pref_key() + '.json')
        pref.parent.mkdir(parents=True, mode=0o700)
        pref.write_text(json.dumps({'schema': 1, 'agent': agent}, separators=(',', ':')) + '\n')
        (legacy / 'projects').write_text(str(self.proj) + '\n')
        return legacy

    def test_normal_launch_migrates_and_keeps_remembered_cli(self):
        legacy = self.make_legacy_state('codex')
        self.approve_codex_in(legacy)
        result = self.run_c3c(str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if '安全に移行できない' in result.stderr:
            # RENAME_NOREPLACE 非対応の FS では旧 state を使い続ける（S-6 が検査する経路）。
            self.skipTest('この環境では RENAME_NOREPLACE が使えない')
        self.assertFalse(os.path.lexists(legacy))
        self.assertTrue((self.state_dir / 'projects').is_file())
        (run,) = self.main_runs()
        self.assertEqual(run['env']['CC_AGENT'], 'codex')
        self.assertIn('移行しました', result.stderr)

    def approve_codex_in(self, base):
        record = base / 'mcp-approvals' / 'codex' / self.project_name() / 'project-config.json'
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({'protocol_version': 2, 'hash': HASH_A}, separators=(',', ':')) + '\n')

    def test_check_reads_legacy_ledger_without_writing(self):
        legacy = self.make_legacy_state()
        before = self.snapshot(self.home)
        result = self.run_c3c('--check')
        self.assertIn(f'=== {self.proj} ===', result.stdout)
        self.assertIn('[WARN] 旧 state', result.stdout)
        self.assertEqual(self.snapshot(self.home), before)
        self.assertTrue(legacy.is_dir())
        self.assertFalse(os.path.lexists(self.state_dir))

    def test_clean_project_does_not_migrate(self):
        legacy = self.make_legacy_state()
        result = self.run_c3c('--clean', str(self.proj))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(legacy.is_dir())
        self.assertFalse(os.path.lexists(self.state_dir))
        self.assertNotIn(str(self.proj) + '\n', (legacy / 'projects').read_text())

    def test_clean_all_removes_approvals_and_ledger_of_legacy_symlink_state(self):
        # 新旧が併存し、旧がディレクトリへの symlink の配置でも、旧の承認記録と台帳を消す（選択記憶は残す）。
        real = self.root / 'legacy-real'
        real.mkdir()
        (real / 'mcp-approvals').mkdir()
        (real / 'mcp-approvals' / 'x').write_text('a')
        (real / 'projects').write_text(str(self.proj) + '\n')
        (real / 'agent-preferences').mkdir()
        (self.home / '.local/state').mkdir(parents=True, exist_ok=True)
        (self.home / '.local/state/claude-container').symlink_to(real)
        self.state_dir.mkdir(parents=True)
        result = self.run_c3c('--clean')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((real / 'mcp-approvals').exists())
        self.assertFalse((real / 'projects').exists())
        self.assertTrue((real / 'agent-preferences').is_dir())
        self.assertTrue((self.home / '.local/state/claude-container').is_symlink())
```

`test-build.sh` の `run_launcher_tests()` に新 suite を登録する（`test_project_images.py` の check の直後）。登録しないと `--launcher-only` と CI で走らない:

```bash
  check "state directory の移行（遷移表・RENAME_NOREPLACE・errno の対応・同一性・check/clean の無移行）" env PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "${SCRIPT_DIR}/tests" -p "test_state_migration.py"
```

README「変更後の確認」節の `--launcher-only` の説明に、`test_state_migration.py`（単独では `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_state_migration.py -v`）を 1 文で足す。

`test_normal_launch_migrates_and_keeps_remembered_cli` は `approve_codex_in` を旧 state に置き、移行後の Codex 経路で確認プロンプトが出ずに本起動へ進む（承認記録が引き継がれた）ことも兼ねる。fixture の既定 `self.state`（`preflight` が `protocol()`）と `HASH_A` が一致していることを前提にしている。

- [ ] **Step 6: テストを通す**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_state_migration.py' -v && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_c3c_launch.py' -v && ./lint.sh && ./test-build.sh --launcher-only`
Expected: 全 PASS（`test_real_rename_noreplace_moves` は RENAME_NOREPLACE 非対応の FS なら skip と表示）、`lint OK`、FAIL 0。

- [ ] **Step 7: コミット**

```bash
git add c3c tests/test_state_migration.py tests/test_c3c_launch.py tests/test_project_images.py test-build.sh tests/ README.md
git commit -m "feat: state directory を ~/.local/state/c3c へ通常起動で移行する"
```

---

### Task 5: label を `io.c3c.*` にし、旧 label へ fallback する

**Files:**
- Modify: `Dockerfile.claude:385-388,405-406,423-429`
- Modify: `c3c`（`guard_ipv6()` 772、`guard_asset_drift()` 2437-2438・2450 のコメント）
- Modify: `project-images.py:14-15,160-171,239-243`
- Modify: `docs/superpowers/specs/2026-09-27-rename-legacy-identifiers-design.md`（`relevant` 判定の 1 行。下記）
- Test: `tests/test_project_images.py`、`test-build.sh`（fake podman の `image inspect`）

**Interfaces:**
- Produces: `image_label <suffix>`（`c3c`）。`$IMAGE_NAME` の `io.c3c.<suffix>` を出力し、空なら `claude-container.<suffix>` を出力する。単独のキー（`asset-hash`・`base-image`・`ipv6-support`）専用。由来 label には使わない。
- Produces: `project-images.py` の `provenance_values(labels)` → `(values, partial)`。`values` は `[metadata, path, name]` を新の組か旧の組のどちらか一方から取ったもの、`partial` は新の組のキーが一部だけある（不完全な新の組）とき True。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_project_images.py`: 定数に `NEW_LABEL = 'io.c3c.project-'` を足し、`item()` に `namespace` 引数を足す:

```python
    def item(self, path, image_id=IMAGE_A, labels=True, namespace=LABEL):
        key = reference_key(path)
        metadata = {namespace + 'metadata': '1', namespace + 'path': path,
                    namespace + 'name': key} if labels else {'claude-container.asset-hash': 'old'}
        ...
```

テストを足す:

```python
    def test_new_namespace_labels_are_cleaned(self):
        # 台帳から対象を外し、新 label だけが由来の根拠になる形にする（台帳に残すと、新 label を読まない
        # 旧実装でも名前と台帳の legacy 照合で清掃され、実装前から緑になる）。
        self.ledger.write_text(self.live + '\n')
        self.before = self.ledger.read_bytes(), self.ledger.stat().st_mode
        self.state['images'] = [self.item(self.missing, namespace=NEW_LABEL)]
        result = self.run_helper(clean=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state['images'], [])

    def test_partial_new_group_with_empty_value_is_invalid(self):
        # 新の組のキーが一部だけ（値は空）で旧の組が完全 → 新の組を選び、不完全なので invalid（旧で補わず、
        # 値が全部空だからといって台帳の legacy 照合へも落とさない）。
        image = self.item(self.missing)
        image['Labels'][NEW_LABEL + 'metadata'] = ''
        self.state['images'] = [image]
        self.assert_kept(self.run_helper(clean=True))

    def test_incomplete_new_group_does_not_borrow_from_complete_old_group(self):
        image = self.item(self.missing)                       # 旧の組は完全
        image['Labels'][NEW_LABEL + 'metadata'] = '1'          # 新の組は不完全（path・name なし）
        self.state['images'] = [image]
        self.assert_kept(self.run_helper(clean=True))

    def test_new_group_wins_over_old_group_pointing_elsewhere(self):
        image = self.item(self.live)                           # 旧の組は存在するパス
        image['Labels'].update({NEW_LABEL + 'metadata': '1', NEW_LABEL + 'path': self.missing,
                                NEW_LABEL + 'name': reference_key(self.missing)})
        image['Names'] = [f'localhost/{reference_key(self.missing)}_claude-auth-workspace:latest']
        self.state['images'] = [image]
        result = self.run_helper(clean=True)                   # 新の組（欠落パス）で判定され、清掃される
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state['images'], [])
```

`test_new_group_wins_over_old_group_pointing_elsewhere` は、`image_name(self.missing)` が `Names` と一致しないと `labeled` にならないので `Names` を上書きしている。旧実装では旧の組（live）と台帳の名前一致（missing）で候補が 2 つになり invalid で残るので、実装前は赤。

`test-build.sh` の fake podman（`launcher_sandbox_init`）の `image inspect` 分岐に新 label の応答を足す:

```bash
    if [[ "\$*" == *io.c3c.ipv6-support* ]]; then printf '%s\n' "\${TEST_IPV6_NEW_SUPPORT-}"; fi
    if [[ "\$*" == *io.c3c.asset-hash* ]]; then printf '%s\n' "\${TEST_ASSET_HASH_NEW-}"; fi
    if [[ "\$*" == *claude-container.asset-hash* ]]; then printf '%s\n' "\${TEST_ASSET_HASH_OLD-}"; fi
    if [[ "\$*" == *io.c3c.base-image* ]]; then printf '%s\n' "\${TEST_BASE_IMAGE_NEW-}"; fi
    if [[ "\$*" == *claude-container.base-image* ]]; then printf '%s\n' "\${TEST_BASE_IMAGE_OLD-}"; fi
```

L 系のテストはすべて、`run_ipv6_launcher_tests()` の末尾（最後の check「IPv6=1 の build と run は同じ override を使う」とそのログ出力の後、`launcher_sandbox_cleanup` の直前）に置く。途中に入れると、L-3 以降の `rm -f` が後続の既存テストの `IPv6=1` の env を消して壊す。まず IPv6 の新優先と fallback（L-1・L-2・L-7）:

```bash
  printf 'C3C_IPV6=1\n' > "$proj/.claude-container.d/env"
  run_launcher TEST_IPV6_NEW_SUPPORT=1 TEST_IPV6_SUPPORT=
  check "L-1: 新 label io.c3c.ipv6-support だけでも IPv6 対応と判定する（rc=$rc）" bash -c "[ $rc -eq 0 ]"
  run_launcher TEST_IPV6_NEW_SUPPORT= TEST_IPV6_SUPPORT=
  check "L-2: 新旧どちらの label も無ければ IPv6 を拒否する（rc=$rc）" bash -c "[ $rc -ne 0 ]"
  run_launcher TEST_IPV6_NEW_SUPPORT=0 TEST_IPV6_SUPPORT=1
  check "L-7: 新 label が 1 以外なら、旧 label が 1 でも IPv6 を拒否する（新優先。rc=$rc）" bash -c "[ $rc -ne 0 ]"
```

（`run_launcher` は引数を env として渡すので、fake podman の `TEST_*` に届く。既存テストが使う変数名と `.claude-container.d` の fixture に合わせる。）

単独キーの新優先を、新旧に**異なる値**を与えて検査する（L-3〜L-6）。正しい値は、1 回起動して compose へ渡った `ASSET_HASH`・`BASE_IMAGE` から取る:

```bash
  rm -f "$proj/.claude-container.d/env"
  run_launcher
  local real_hash real_base
  real_hash=$(sed -n 's/^ASSET_HASH=//p' "$root/compose-env")
  real_base=$(sed -n 's/^BASE_IMAGE=//p' "$root/compose-env")
  run_launcher TEST_ASSET_HASH_NEW="$real_hash" TEST_ASSET_HASH_OLD=bogus
  check "L-3: asset-hash は新 label を優先する（旧が違っても drift なし）" \
    bash -c "! printf '%s' \"\$0\" | grep -q '境界アセット.*変更されています'" "$out"
  run_launcher TEST_ASSET_HASH_NEW=bogus TEST_ASSET_HASH_OLD="$real_hash"
  check "L-4: asset-hash の新 label が違えば、旧が一致していても drift を出す" \
    bash -c "printf '%s' \"\$0\" | grep -q '境界アセット.*変更されています'" "$out"
  run_launcher TEST_ASSET_HASH_NEW= TEST_ASSET_HASH_OLD="$real_hash"
  check "L-5: 新 label が空なら旧 label へ fallback（drift なし）" \
    bash -c "! printf '%s' \"\$0\" | grep -qE '境界アセット.*変更されています|ハッシュラベルがありません'" "$out"
  run_launcher TEST_ASSET_HASH_NEW="$real_hash" TEST_BASE_IMAGE_NEW=bogus TEST_BASE_IMAGE_OLD="$real_base"
  check "L-6: base-image も新 label を優先する" \
    bash -c "printf '%s' \"\$0\" | grep -q 'ベースイメージの設定.*異なります'" "$out"
  run_launcher TEST_ASSET_HASH_NEW="$real_hash" TEST_BASE_IMAGE_NEW= TEST_BASE_IMAGE_OLD=bogus
  check "L-8: base-image の新 label が空なら旧 label へ fallback する（旧が違えば警告）" \
    bash -c "printf '%s' \"\$0\" | grep -q 'ベースイメージの設定.*異なります'" "$out"
  printf '%s\n' "$out" >> "$LOG_FILE"
```

（`guard_asset_drift()` の WARNING 文言は `c3c` の現行のもの。`ASSET_HASH`・`BASE_IMAGE` が compose-env に出ることは既存の E 系テストの前提と同じ。）単独キーの「無い」は、キーの欠落と空値の両方を指す（`podman image inspect` の `index` は欠落キーにも空文字を返し、両者を区別できないため）。spec の「label」節の該当行も「空か欠落なら旧を読む」に直す。

- [ ] **Step 2: 失敗を確認する**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_project_images.py -v 2>&1 | tail -15; ./test-build.sh --launcher-only; grep -E 'L-[0-9].*\[FAIL\]' .claude/test-results/*.log`
Expected: 新 label の 4 テスト（`test_new_namespace_labels_are_cleaned`・`test_partial_new_group_with_empty_value_is_invalid`・`test_incomplete_new_group_does_not_borrow_from_complete_old_group`・`test_new_group_wins_over_old_group_pointing_elsewhere`）と L-1・L-3・L-4・L-6・L-7 が FAIL（L-4 は旧実装では旧 label＝一致で drift なし → FAIL。L-2・L-5・L-8 は旧 label だけを読む旧実装でも緑の対照）。

- [ ] **Step 3: 実装する**

`Dockerfile.claude`:

```dockerfile
ARG ASSET_HASH=unknown
# 改名 第 1 段: 新 label（io.c3c.*）と旧 label（claude-container.*）の両方を書く。旧版の c3c へ戻したときも
# ドリフト検知・IPv6 対応確認・--clean-missing が働くように（第 2 段で旧 label を外す）。
LABEL io.c3c.asset-hash="${ASSET_HASH}" \
      claude-container.asset-hash="${ASSET_HASH}"
# 旧 entrypoint が IPv6 モードを無視して起動するのを launcher で防ぐ。
LABEL io.c3c.ipv6-support="1" \
      claude-container.ipv6-support="1"
...
ARG BASE_IMAGE
LABEL io.c3c.base-image="${BASE_IMAGE}" \
      claude-container.base-image="${BASE_IMAGE}"
...
LABEL io.c3c.project-metadata="${CC_PROJECT_METADATA}" \
      io.c3c.project-path="${CC_PROJECT_PATH}" \
      io.c3c.project-name="${CC_PROJECT_NAME}" \
      claude-container.project-metadata="${CC_PROJECT_METADATA}" \
      claude-container.project-path="${CC_PROJECT_PATH}" \
      claude-container.project-name="${CC_PROJECT_NAME}"
```

由来 label は全命令の最後の単一 `LABEL` のまま、asset-hash は CACHEBUST を消費する RUN より後の同じ位置のまま（`docs/development-invariants.md` の由来 label・`ARG ASSET_HASH` の節）。

`c3c`（`guard_ipv6()` より前）に追加する:

```bash
# 単独のキーの image label を新名（io.c3c.<suffix>）優先で読み、空なら旧名（claude-container.<suffix>）を読む
# （改名 第 1 段。第 1 段より前のイメージは旧名だけを持つ）。由来 label（project-*）は組単位で選ぶ必要があるので
# ここでは扱わない（project-images.py）。inspect の失敗は従来どおり空として扱う。
image_label() {
  local value
  value=$(podman image inspect --format "{{index .Labels \"io.c3c.$1\"}}" "$IMAGE_NAME" 2>/dev/null || true)
  if [[ -z "$value" ]]; then
    value=$(podman image inspect --format "{{index .Labels \"claude-container.$1\"}}" "$IMAGE_NAME" 2>/dev/null || true)
  fi
  printf '%s' "$value"
}
```

`guard_ipv6()`: `support=$(image_label ipv6-support)`。`guard_asset_drift()`: `recorded_hash=$(image_label asset-hash)`、`recorded_base_image=$(image_label base-image)`。2450 行目のコメントの label 名を `io.c3c.base-image` にする。

`project-images.py`:

```python
NEW_PREFIX = 'io.c3c.project-'
LEGACY_PREFIX = 'claude-container.project-'
SUFFIXES = ('metadata', 'path', 'name')
NEW_LABELS = tuple(NEW_PREFIX + suffix for suffix in SUFFIXES)
LEGACY_LABELS = tuple(LEGACY_PREFIX + suffix for suffix in SUFFIXES)


def provenance_values(labels):
    """由来 label を組単位で選ぶ（改名 第 1 段）。新の組のキーが 1 つでもあれば新の組だけを使い、
    旧の組で補わない。新の組のキーが一部だけなら partial=True（値が空でも、台帳の legacy 照合へ落とさず
    invalid にする）。三つとも揃って空なのは直接ビルドの既存契約で、従来どおり扱う。
    新の組が 1 つも無いときだけ旧の組（旧の組の扱いは従来と同じ）。"""
    present = [key in labels for key in NEW_LABELS]
    if any(present):
        return [labels.get(key, '') for key in NEW_LABELS], not all(present)
    return [labels.get(key, '') for key in LEGACY_LABELS], False
```

`provenance()` の先頭を次にする:

```python
    values, partial = provenance_values(item['labels'])
    matches = {path for path in ledger if image_name(path) in item['names']}
    if partial:
        return matches, 'invalid'
    if not any(values):
        return matches, 'legacy' if len(matches) == 1 else 'unknown'
```

`relevant` の `any(item['labels'].get(k) for k in LABELS)` は `any(provenance_values(item['labels'])[0])` にする。名前なしイメージの判定は従来の `claude-container.` 前方一致を残し、新の由来 label のキーも加える:

```python
            relevant = (any(k.startswith('claude-container.') for k in item['labels'])
                        or any(k in item['labels'] for k in NEW_LABELS)
                        or any(IMAGE_NAME.fullmatch(n) for n in item['history']))
```

（`io.c3c.` の前方一致にしない — `io.c3c.codex-audit-protocol` は既存の全イメージに付く。旧 label の前方一致を残すのは、第 1 段より前の名前なしイメージの判定を狭めないため。）`LABELS` の他の参照が残っていないこと（`grep -n LABELS project-images.py`）。

spec の「label」節の `relevant` の 1 行を、上の実装（旧 `claude-container.` 前方一致を維持し、新の由来 label キーを加える。`io.c3c.` 前方一致にはしない）に合わせて直す。

- [ ] **Step 4: テストを通す**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_project_images.py -v && ./lint.sh && ./test-build.sh --launcher-only`
Expected: 全 PASS、`lint OK`、FAIL 0。

- [ ] **Step 5: コミット**

```bash
git add Dockerfile.claude c3c project-images.py tests/test_project_images.py test-build.sh docs/superpowers/specs/2026-09-27-rename-legacy-identifiers-design.md
git commit -m "feat: image label を io.c3c.* にし、旧 label へ fallback する"
```

---

### Task 6: 秘密を新旧両方のパスへ `:ro` でマウントする

**Files:**
- Modify: `compose.yml:96`、`lint.sh:241`
- Test: `tests/test-lint-compose-checks.sh`（必要なら fixture）、`lint.sh` 自体

**Interfaces:**
- Produces: コンテナ内の `/home/node/.config/c3c/secrets` と `/home/node/.config/claude-container/secrets` に同じ `SECRETS_DIR` が `:ro`。`entrypoint.sh`・`git-askpass.sh` の `SECRETS_MOUNT` は旧パスのまま。

- [ ] **Step 1: lint の検査を先に足す（失敗を確認する）**

`lint.sh:241` の検査対象に 2 つのパスを足す:

```bash
    for target in /etc/claude-container/codex-mcp-approved.json /etc/claude-container/mcp-approved-hash /etc/claude-container/claude-project-approved.json /home/node/.gitconfig /home/node/.config/c3c/secrets /home/node/.config/claude-container/secrets; do
```

Run: `./lint.sh; echo rc=$?`
Expected: `/home/node/.config/c3c/secrets` の `:ro` が無い ERROR で rc≠0（podman が無い環境では Compose 検証がスキップされるので、その場合は `not run` として CI かホストで確認する）。

- [ ] **Step 2: compose を変える**

`compose.yml` の秘密のマウントを 2 行にする:

```yaml
      # 改名 第 1 段: 新パス（~/.config/c3c/secrets）と旧パスの両方へ同じ SECRETS_DIR を :ro で載せる。
      # 利用者のスクリプト・MCP 設定が第 2 段までに新パスへ移れるよう、-b していない旧イメージでも新パスを
      # 使えるようにする。entrypoint.sh・git-askpass.sh は第 1 段では旧パスを読む（旧イメージとの整合）。
      - ${SECRETS_DIR:-/dev/null}:/home/node/.config/c3c/secrets:ro
      - ${SECRETS_DIR:-/dev/null}:/home/node/.config/claude-container/secrets:ro
```

- [ ] **Step 3: lint を通す**

Run: `./lint.sh && bash tests/test-lint-compose-checks.sh`
Expected: `lint OK`、compose checks の PASS。

- [ ] **Step 4: コミット**

```bash
git add compose.yml lint.sh
git commit -m "feat: SECRETS_DIR を新パス ~/.config/c3c/secrets にも :ro でマウントする"
```

---

### Task 7: 文書を更新する

**Files:**
- Modify: `README.md`、`docs/development-invariants.md`、`examples/c3c/env.example`、`AGENTS.md`（必要な場合だけ）

- [ ] **Step 1: README**

次を更新する（`grep -n -E 'claude-container|CLAUDE_CONTAINER' README.md` を上から見て、下の方針で個別に判断する）:
- 秘密の案内（315・317・324・329 行付近）を新パスにする: 例 `~/.config/c3c/secrets.d/<project>`、コンテナ内 `/home/node/.config/c3c/secrets`。旧パスも第 1 段では同じ内容が読めることを 1 文で書く。
- state のパス（168・437・445・544 行付近）を `~/.local/state/c3c/...` にする。
- label 名（156・503 行付近）を `io.c3c.*` にし、第 1 段では旧名も併記されることを書く。
- 新しい節「旧名 claude-container の識別子からの移行（v15.1 系）」を「旧 `.claude-container.d/` からの移行」の後に置く。内容: 対応表（env キー・state・label・秘密のパス）、旧名は `WARNING` 付きで動くこと、env キーの新旧併存は `ERROR`、state は通常起動で自動移行（`--check`・`--clean` は移さない。上書きしない rename が使えない環境は旧を使い続けて手動 `mv` を案内）、旧版へ戻したとき（env キーの `C3C_*` は無視されて安全側、state は空から作り直され承認の確認がもう一度出る、新版へ戻すと「両方ある」の WARNING）、`-b` 推奨（ドリフト WARNING）、次のメジャー版の予告と、その前に `c3c --check --clean-missing` を実行しておくこと。
- README 132 行目付近（旧入口からの移行の「設定・認証・承認記録…は維持」）と 529 行目付近（c3c 入口の説明）で、内部の保存先の名前を述べている箇所があれば、第 1 段の state の移行と矛盾しないよう直す。
- 旧入口 `claude-container` の移行表、upstream の帰属、過去の Issue URL は変えない。

- [ ] **Step 2: `docs/development-invariants.md`**

- state directory（`resolve_state_dir()`・`rename_noreplace()`）: 通常起動だけ移行、lstat、`RENAME_NOREPLACE` 必須、同一性の確認、`--check` は無書込・`--clean` は無移行、readonly の位置（#39）。
- env キーの対の解決（`guard_env_key_renames()`）: 新旧併存の拒否、旧キーの unset、`C3C_*` を readonly にしない、compose は新キーから新旧両方の名前へ補間。
- label: 単独キーの `image_label()`、由来 label の組単位（`provenance_values()`）、新旧 6 つを最後の単一 LABEL に。
- 秘密の二重マウントの `:ro`（`lint.sh` が検査）。
- `CLAUDE_CONTAINER_DIR` → `C3C_DIR`、旧 label 名・旧 state パスの記述を新名に（`grep -n -E 'claude-container|CLAUDE_CONTAINER' docs/development-invariants.md`。`.claude-container.d` と `/etc/claude-container` は第 1 段では残る）。
- コードのコメントに残る旧キー名も新キーにする: `init-firewall.sh:17`（`CLAUDE_CONTAINER_NO_FIREWALL=1 で無効化可`）、`entrypoint.sh:118`（Task 2 で直していなければ）。`git grep -n -E 'CLAUDE_CONTAINER_(NO_FIREWALL|IPV6)' -- . ':!docs/superpowers'` の残りが、互換のための実装・テスト・README の旧キーの行だけであること。

- [ ] **Step 3: `examples/c3c/env.example`**

`SECRETS_DIR=~/.config/claude-container/secrets.d/claude-container` を `SECRETS_DIR=~/.config/c3c/secrets.d/c3c` にする。

- [ ] **Step 4: lint とコミット**

Run: `./lint.sh && ./test-build.sh --launcher-only`
Expected: `lint OK`、FAIL 0（E7 の表の一致を含む）。

```bash
git add README.md docs/development-invariants.md examples/c3c/env.example init-firewall.sh entrypoint.sh
git commit -m "docs: 旧名 claude-container の識別子からの移行（第 1 段）を README と不変条件に書く"
```

---

### Task 8: 全体の検証（実機を含む）

**Files:** なし（検証と記録だけ）

- [ ] **Step 1: 自動テスト**

Run: `./lint.sh && ./test-build.sh --launcher-only && ./test-build.sh --validator-only && bash examples/hooks/tests/test-block-pr-approve.sh`
Expected: すべて成功。結果をそのまま記録する。

`init-firewall.sh` はコメントだけの変更なので、その回帰テスト（`--launcher-only` に含む）で足りる。

- [ ] **Step 2: 実イメージのビルドと label（ホスト、実 Podman）**

Run: `./test-build.sh --build-only`、続けて `podman image inspect --format '{{json .Labels}}' localhost/claude-test | jq 'with_entries(select(.key|test("c3c|claude-container")))'`
Expected: `io.c3c.asset-hash`・`io.c3c.base-image`・`io.c3c.ipv6-support`・`io.c3c.project-*` と旧名の 6 つが並ぶ（直接ビルドなので project-* は空）。

続けて `./test-build.sh --config-ro-only`（Task 6 で `compose.yml` のマウントを変えたため。README「変更後の確認」節）と、`tests/test-runtime.sh` を使う実コンテナ検証（Task 3 で `C3C_DIR` に変えたため。実行方法は `docs/runtime-ci.md`。ホストで回せなければ runtime workflow の手動実行で代える）を行う。

- [ ] **Step 3: 新旧の組み合わせ（ホスト、実 Podman。持ち主と実施）**

事前に `cp -a ~/.local/state/claude-container ~/c3c-state-backup-2026XXXX` で退避する。

1. 新 launcher × `-b` していない旧イメージ: 利用側プロジェクトの `.c3c/env` を `C3C_NO_FIREWALL=1` にして `c3c claude <dir>` → コンテナ内で外部への通信が許可リスト外でも通ること（例 `curl -sI https://example.com`）と、起動時の `WARNING: エグレスファイアウォールは無効です` を確認。`C3C_IPV6=1` でも同様に IPv6 が有効になること。旧キーでも同じこと。
2. 秘密: コンテナ内で `ls /home/node/.config/c3c/secrets /home/node/.config/claude-container/secrets` が同じ内容で、書き込みが拒否されること。
3. state: 初回の通常起動で `WARNING: state を ... へ移行しました` が出て、`~/.local/state/c3c` に台帳・承認記録・選択記憶があり、MCP の確認プロンプトが再度出ないこと。
4. 旧 launcher（第 1 段の直前のタグ v15.0.0 の checkout）× 第 1 段で `-b` した新イメージ: 旧キー（`CLAUDE_CONTAINER_NO_FIREWALL=1`）で firewall が無効になり、`CLAUDE_CONTAINER_IPV6=1` で IPv6 が有効になること（新 entrypoint の旧キー fallback）。
5. `-b` 前の旧イメージで `c3c --check <dir>` がドリフトの `[WARN]` を出すこと。

実施できなかった項目は `not run` と理由を記録する。fake Podman の成功で代替しない。

- [ ] **Step 4: 記録**

結果を PR 本文に書く。SemVer は MINOR（v15.1.0）を提案する（root `AGENTS.md`「バージョン管理」。タグは持ち主の承認後、`release-tag` skill）。

---

区分: 境界 — ファイアウォールを無効化する env キー、承認記録（state）と秘密のマウント先、`docs/development-invariants.md` の不変条件に触れるため。計画・実装完了時（PR 前）・PR 後の 3 段階で Codex と Claude の二重レビューを行う。
推奨実装: Opus — 秘密を読む経路（`SECRETS_DIR` のマウント先）と、承認記録を失いうる state の移行という境界の変更を含む（判定基準の 2）。Sonnet を推さないのは、Task 4 の遷移表・同一性確認と Task 5 の組単位の選択で、不変条件と突き合わせる判断が実装中に残るため。Codex を推さないのは、Task 8 の実機確認がホストの実 Podman と持ち主の実 state を要し、`~/.local/state` の移行を伴うため。

## 計画レビューの記録

- 1 巡目（対象 e793b00）: Codex（gpt-6-astra、`codex exec --sandbox read-only`。依頼文の「コマンド実行はしない」で読めず未実施になったため、読み取り専用コマンドを許可して再実行）は「修正後に渡せる」、Critical 0・Important 7・Minor 3。Claude（claude-opus-5-5、headless 読み取り専用）は「修正後に渡せる」、Critical 0・Important 4・Minor 12。共通の Important は E-R2 の期待の不成立、compose 補間の未検証、Task 2 のテストが entrypoint 後半まで走る点、実装前から緑のテスト。Codex 固有は空値の部分的な新由来 label、symlink の旧 state の清掃漏れ、新 suite の未登録、単独 label の新優先の未検証。Claude 固有は旧 state がマウントポイントのときの `EBUSY`。いずれも反映した。spec の変更（`relevant` 判定と単独 label の「空か欠落」）は Task 5 で行う。
- 確認限定巡（対象 c06b00a）: Claude は前回 16 件すべて「直った」、新たに L 系テストの挿入位置の曖昧さを指摘。Codex は Important 6 が「一部」（IPv6 の新旧異値の優先と base-image の旧 fallback の検査）、Minor 2 が「一部」（launcher の移行テストの非対応時 skip）。いずれも反映した（L-7・L-8、挿入位置の明記、skip）。
- 確認限定巡 2 回目（対象 41747fa）: Codex・Claude とも前回の残りが「直った」、判定「実装に渡せる」。計画レビューは収束。
