# c3c 第0A段階: 秘密なし事前調査（版・設定源・Git 相対リンク・Codex 登録と MCP 起動観測）の実行計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> 実行担当: Opus（末尾「実装」参照）。製品コードを書く計画ではなく、仕様第0段階（G2・G3）のうち **秘密も実認証も要らない部分だけ** を実測する調査計画である。実認証・製品 entrypoint 経由の境界・両 CLI の同会話移動は第0B段階（本計画の結果を見てから別計画）とし、本計画の完了を G3 完了・製品実装許可・第1/第3段階の前提充足と扱わない。元仕様 §4 の要件は取り消さず、未実測項目は Task 4 の表に残す。

**Goal:** 使い捨て領域と既存イメージだけを使い、ホスト/イメージの版、Codex の設定源と CLI 表面、Git 相対リンクの双方向互換、秘密なし `--network none` での Codex 設定登録・無害 MCP プロセスの起動有無・モデル不要 sandbox コマンドの実行経路を「成立／不成立／not run（理由）」で記録する。

**Architecture:** 全プローブは `mktemp -d` 配下 `$ROOT` の脚本と、実行担当が明示選択した既存イメージ ID（`--pull never`）で行う。上流コード（codex・claude・コンテナ内 git）が起動される場所はコンテナ内 `--network none`・秘密なし・製品 ENTRYPOINT（setpriv+tini）維持・CMD のみ差し替えに限る。製品 `entrypoint.sh`（firewall・MCP ゲート・秘密配線）は通過しないので、本計画の観測を最終境界証明には使わない。作成資源は台帳に記録し、後始末は台帳の資源に限る。TDD は対象外。

**Tech Stack:** bash、rootless Podman（ホスト事前観測 2026-09-20: 5.8.6、rootless=true）、Git（ホスト 2.53.0）、既存の claude-container イメージ（`debian:stable` ベース、Claude Code 2.1.278・codex-cli 0.155.1 が仕様 §3 のホスト実測値）、コンテナ内 python3（`tomllib`）。

**Spec:** [docs/superpowers/specs/2026-09-20-c3c-incremental-design.md](../specs/2026-09-20-c3c-incremental-design.md) §3・§4（G1〜G4）・§7・§9・§11。

## Global Constraints

- 「既存の作業中 worktree を実験対象にしない」「確認用の実行やプローブにも、対象、変更範囲、期待結果、元へ戻す方法を定める」（仕様 §4）。
- 「`CODEX_DIR/config.toml` だけを見て網羅できたと扱わない」「設定解析不能・実効設定の判定不能を黙って許可へ落とさない」「失敗を理由に自動的に広い権限へ切り替えない」（G3）。
- 「既存の `.claude/worktrees/` や兄弟ディレクトリの worktree は列挙・診断し、黙って移動・修復しない」「ホーム全体の mount や Podman socket の公開は解決策にしない」（G2）。
- 「子プロセス内の `cd` や `codex -C` の起動成功だけで、既存会話の基点切替成功と判断しない」（§7）。本計画は移動を実測しない。
- 上流コードの起動はコンテナ内 `--network none`・秘密なしに限る。ホストで `codex`・`claude` を起動しない（版は仕様 §3 の 2026-09-20 実測値を転記）。
- 実認証・ホスト実設定（`~/.codex`・`~/.claude.json`・`~/.claude`）の共有・コピー・参照を一切しない。Podman の `-v` は `crun` が生成する 3 本以外に増やさない。
- 新規ビルドをしない。`podman build`・`podman rmi`・`podman image prune`・`podman system prune`・`claude-container --clean`・`--network` の none 以外・`CLAUDE_CONTAINER_NO_FIREWALL`・`--sandbox danger-full-access`・`$ROOT/repo` 以外への `git worktree prune|repair|remove` を実行しない。help に無い引数・サブコマンドを推定で使わない。
- 製品ファイルを変更しない。追加するのは結果記録 `$RESULTS` 1 ファイルのみ。自動 commit・push をしない。
- 公開文書にホスト固有パス・既存 worktree/ブランチ名・イメージの Repository 名（プロジェクト名を含む）・private Issue を書かない。転記時は `$ROOT`・`$CC` の実値を変数名に置換する。
- 未実測を成功扱いしない。未起動・未到達を保護成功と解釈しない。

## Review Focus

1. **同じ宛先への重複 mount で起動失敗**: `crun` が `/workspace` を `-w` の 1 本だけ生成し、Task 1 Step 4 の smoke で `inspect` の Binds を確認する。
2. **旧 Git が相対 back-link を誤解釈**: Task 2 で両側の生の `gitdir` 内容と `worktree list` を記録し、`$ROOT/repo` 以外で prune を実行しない。
3. **マーカー不在の誤読**: MCP サーバーが認証失敗で起動前に終了した場合と起動しない仕様を区別できない。Task 3 Step 6 は不在を「未到達（0B 必須）」に留め、マーカーは最初の行で書いて `sync` する。
4. **権限エラーを sandbox 成功と誤認**: Task 3 Step 7 は同じユーザー・mount で素の書き込み対照を先に取る。
5. **entrypoint.sh 不通過を境界証明と誤認**: Task 1 Step 4 で ENTRYPOINT 維持と CMD 差し替えを `inspect` で示し、`$RESULTS` §0 に「firewall・cap 剥奪後の実効・秘密配線は未通過」と明記する。

---

## 共通の前提

- `$CC`: claude-container の checkout 絶対パス。`$ROOT`: `mktemp -d` の使い捨て領域。`$RUN_ID`: 一意名の接頭辞。`$IMAGE`: 選択した既存イメージ ID。`$RESULTS`: `$CC/docs/superpowers/plans/2026-09-20-c3c-phase0a-results.md`。
- 全ブロックは同じ専用 bash セッションで順に実行し、先頭で `source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"` を行う。準備失敗時の `exit` は専用 shell を終了して後続の誤実行を防ぐためのもの。shell を替えた場合は Task 1 Step 1 の出力にある `export ROOT=...` を再実行する。
- 記録単位は「条件／観測（ログ引用）／判定／残留物」。判定は成立・不成立・not run（理由）のみ。
- 途中終了した場合は再開前に `"$ROOT/bin/cleanup"` を実行する（台帳のコンテナ除去とログ退避のみ。`$ROOT` は消さない）。

## Task 1: 使い捨て基盤（helper・イメージ選択・版・記録様式）

**Files:**
- Create: `$ROOT/env.sh`、`$ROOT/bin/lib.sh`、`$ROOT/bin/cleanup`、`$ROOT/probe/bin/{mcp-marker.sh,notify-marker.sh}`、`$ROOT/ledger.tsv`、`$RESULTS`
- 参照のみ: `$CC/Dockerfile.claude:276-277`（ENTRYPOINT/CMD）、`$CC/tests/test-runtime.sh:29-31,121-132`（`env -i` と使い捨て領域の流儀）、`$CC/tests/compose.runtime-userns.yml`

**Interfaces:**
- Produces: `hrun <名前> <ホストコマンド...>`、`hgit <git 引数...>`（実設定から隔離したホスト Git）、`crun <名前> -w <host dir> [-c <codex home>] [-t 秒] -- <コンテナ内コマンド...>`、`ledger <種別> <名前>`、`$ROOT/logs/<名前>.{log,rc,inspect}`、`save_markers <名前>` の `<名前>-markers/`（不在/空/内容ありの区別を保持）、マーカー出力 `$ROOT/probe/out/{mcp-started,notify-fired}.log`。

- [ ] **Step 1: 領域・変数・隔離用 Git 設定を作る**

```bash
ROOT=$(mktemp -d /tmp/c3c-0a.XXXXXX); ROOT=$(realpath "$ROOT"); export ROOT
CC=$(env -i PATH="$PATH" HOME="$HOME" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null git -c core.fsmonitor=false -c core.hooksPath=/dev/null rev-parse --show-toplevel)     # claude-container の checkout 内で実行する
RUN_ID="c3c-0a-$$-$(basename "$ROOT" | cut -d. -f2 | tr 'A-Z' 'a-z')"
mkdir -p "$ROOT"/{bin,logs,probe/bin,probe/out,probe/empty-template,home/empty-template,ws-empty,ws-sb,codex-home,codex-home-broken,codex-home-sandbox,repo}
chmod 700 "$ROOT/codex-home" "$ROOT/codex-home-broken" "$ROOT/codex-home-sandbox"
printf '[user]\n\tname = probe\n\temail = probe@example.invalid\n[commit]\n\tgpgsign = false\n[tag]\n\tgpgsign = false\n' > "$ROOT/home/gitconfig"
printf 'export ROOT=%q\nCC=%q\nRUN_ID=%q\nRESULTS=%q\n' "$ROOT" "$CC" "$RUN_ID" "$CC/docs/superpowers/plans/2026-09-20-c3c-phase0a-results.md" > "$ROOT/env.sh"
: > "$ROOT/ledger.tsv"; echo "export ROOT=$ROOT"
```

Expected: `$ROOT/env.sh` に 4 変数（`printf %q` で quote 済み）。`export ROOT=...` の 1 行が表示される。

- [ ] **Step 2: 共通 helper とマーカーを置く**

```bash
source "${ROOT:?}/env.sh"
cat > "$ROOT/bin/lib.sh" <<'EOF'
#!/bin/bash
# 共通 helper。source "$ROOT/env.sh" の後に source する。set -e は使わず、失敗は rc ファイルに残す。
ledger() { printf '%s\t%s\t%s\n' "$(date -Is)" "$1" "$2" >> "$ROOT/ledger.tsv"; }
hrun() {
  local n=$1 rc; shift
  if "$@" > "$ROOT/logs/$n.log" 2>&1; then rc=0; else rc=$?; fi
  printf '%s\n' "$rc" > "$ROOT/logs/$n.rc"
  printf '== %s rc=%s\n' "$n" "$rc"; cat "$ROOT/logs/$n.log"
  return 0  # 観測ラッパー。成功判定は必ず .rc と各 Expected を照合する。
}
save_markers() {
  local n=$1 f dst="$ROOT/logs/$1-markers"
  [[ $n =~ ^[a-zA-Z0-9_-]+$ && ! -e $dst ]] || return 2
  mkdir "$dst" || return 1
  for f in mcp-started.log notify-fired.log; do
    if [[ ! -e $ROOT/probe/out/$f ]]; then
      printf '%s absent\n' "$f" >> "$dst/states" || return 1
    else
      cp "$ROOT/probe/out/$f" "$dst/$f" && cmp "$ROOT/probe/out/$f" "$dst/$f" || return 1
      if [[ -s $dst/$f ]]; then printf '%s present\n' "$f"; else printf '%s empty\n' "$f"; fi >> "$dst/states" || return 1
    fi
  done
}
# hgit: ホスト Git を実ユーザー設定・system 設定・template・署名から隔離する（差し替えは env -i の子プロセス内だけ）
hgit() { env -i PATH="$PATH" HOME="$ROOT/home" LC_ALL=C GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL="$ROOT/home/gitconfig" GIT_TEMPLATE_DIR="$ROOT/home/empty-template" git -c core.fsmonitor=false -c core.hooksPath=/dev/null -c commit.gpgSign=false -c tag.gpgSign=false "$@"; }
# crun: --network none / --pull never / keep-id(実行者→1000) / 製品 ENTRYPOINT 維持で CMD だけ差し替え。mount は /workspace, /probe, 任意の /home/node/.codex の 3 本まで。
crun() {
  local n=$1 ws='' ch='' tmo=120 cname cid rc; shift
  [[ $n =~ ^[a-zA-Z0-9_-]+$ ]] || return 2
  while [[ $# -gt 0 && $1 != -- ]]; do
    [[ $# -ge 2 ]] || return 2
    case $1 in -w) ws=$2;; -c) ch=$2;; -t) tmo=$2;; *) return 2;; esac
    shift 2
  done
  [[ ${1:-} == -- && $# -ge 2 && -n $ws && -n ${IMAGE:-} ]] || { echo "crun: 引数または IMAGE が未設定" >&2; return 2; }
  shift
  [[ $tmo =~ ^[1-9][0-9]*$ && -d $ws ]] || return 2
  case "$(realpath "$ws")/" in "$ROOT/"*) ;; *) echo "crun: mount 元が ROOT 外" >&2; return 2;; esac
  if [[ -n $ch ]]; then
    [[ -d $ch ]] || return 2
    case "$(realpath "$ch")/" in "$ROOT/"*) ;; *) echo "crun: mount 元が ROOT 外" >&2; return 2;; esac
  fi
  [[ ! -e $ROOT/logs/$n.cid && ! -e $ROOT/logs/$n.rc ]] || {
    echo "再試行は別の観測名を使う: $n" >&2; return 2;
  }
  cname="$RUN_ID-$n"
  local v=(-v "$ws:/workspace" -v "$ROOT/probe:/probe")
  [[ -n $ch ]] && v+=(-v "$ch:/home/node/.codex")
  if podman create --cidfile "$ROOT/logs/$n.cid" --name "$cname" \
    --label "c3c.phase0.owner=$RUN_ID" --network none --pull never \
    --userns=keep-id:uid=1000,gid=1000 -w /workspace \
    -e GIT_CONFIG_NOSYSTEM=1 -e GIT_CONFIG_GLOBAL=/dev/null \
    -e GIT_TEMPLATE_DIR=/probe/empty-template \
    -e GIT_AUTHOR_NAME=probe -e GIT_AUTHOR_EMAIL=probe@example.invalid \
    -e GIT_COMMITTER_NAME=probe -e GIT_COMMITTER_EMAIL=probe@example.invalid \
    "${v[@]}" "$IMAGE" "$@" > "$ROOT/logs/$n.create" 2>&1; then rc=0; else rc=$?; fi
  if [[ -s $ROOT/logs/$n.cid ]]; then cid=$(cat "$ROOT/logs/$n.cid"); ledger container "$cid"; fi
  if [[ $rc != 0 ]]; then printf 'create-failed:%s\n' "$rc" > "$ROOT/logs/$n.rc"; cat "$ROOT/logs/$n.create"; return 1; fi
  if ! podman inspect "$cid" --format 'entrypoint={{json .Config.Entrypoint}} cmd={{json .Config.Cmd}} net={{.HostConfig.NetworkMode}} binds={{json .HostConfig.Binds}}' > "$ROOT/logs/$n.inspect"; then
    echo inspect-failed > "$ROOT/logs/$n.rc"; return 1
  fi
  if timeout --signal=TERM --kill-after=20s "$tmo" podman start -a "$cid" > "$ROOT/logs/$n.log" 2>&1; then rc=0; else rc=$?; fi
  printf '%s\n' "$rc" > "$ROOT/logs/$n.rc"
  if ! timeout 30s podman rm -f "$cid" > "$ROOT/logs/$n.rm" 2>&1; then echo "$cid" >> "$ROOT/logs/rm-failed"; fi
  printf '== %s rc=%s\n' "$n" "$rc"; cat "$ROOT/logs/$n.inspect" "$ROOT/logs/$n.log"
}
EOF
cat > "$ROOT/probe/bin/mcp-marker.sh" <<'EOF'
#!/bin/sh
# stdio 型 MCP サーバーの代役。起動の事実だけを最初に記録し、応答せず最大 20 秒で終了する。引数や環境の値は書かない。
out=${PROBE_OUT:-/probe/out}; mkdir -p "$out"
printf '%s pid=%s ppid=%s cwd=%s argc=%s\n' "$(date -Is)" "$$" "$PPID" "$(pwd)" "$#" >> "$out/mcp-started.log"; sync
timeout 20 cat > /dev/null; exit 0
EOF
cat > "$ROOT/probe/bin/notify-marker.sh" <<'EOF'
#!/bin/sh
# notify 等の外部コマンド hook の代役。時刻と引数の個数だけを記録する。
out=${PROBE_OUT:-/probe/out}; mkdir -p "$out"
printf '%s argc=%s\n' "$(date -Is)" "$#" >> "$out/notify-fired.log"; sync
EOF
cat > "$ROOT/bin/cleanup" <<'EOF'
#!/bin/bash
# 台帳のコンテナだけを除去し、ログを $CC/.claude/test-results/<RUN_ID>/ へ退避する（tests/test-runtime.sh と同じ gitignore 対象）。
# イメージ・既存資源には触れない。退避に失敗したら $ROOT を残す。--rm-root を付けた時だけ、退避成功後に $ROOT を消す。
set -uo pipefail; source "$(dirname "$0")/../env.sh"; rc=0
[[ $ROOT == "$(realpath /tmp)"/c3c-0a.* && -d $ROOT && -f $ROOT/ledger.tsv ]] || exit 2
# cidfile も照合する。create 後、ledger 記録前に割り込まれても対象を回収する。
shopt -s nullglob
for cidfile in "$ROOT"/logs/*.cid; do
  name=$(cat "$cidfile")
  [[ $name =~ ^[0-9a-f]{64}$ ]] || { rc=1; continue; }
  if podman container exists "$name"; then
    owner=$(podman inspect "$name" --format '{{index .Config.Labels "c3c.phase0.owner"}}') || { rc=1; continue; }
    [[ $owner == "$RUN_ID" ]] || { echo "所有印不一致: $name"; rc=1; continue; }
    timeout 30s podman rm -f "$name" || { echo "残留: $name"; rc=1; }
  else
    exists_rc=$?
    [[ $exists_rc == 1 ]] || { echo "存在確認に失敗: $name rc=$exists_rc"; rc=1; }
  fi
done
dest="$CC/.claude/test-results/$RUN_ID"
if mkdir -p "$dest" && cp -r "$ROOT/logs" "$ROOT/ledger.tsv" "$ROOT/env.sh" "$ROOT/bin" "$ROOT/probe/out" "$dest/"; then echo "退避先: $dest"; else echo "退避失敗: $ROOT を削除しない"; exit 1; fi
if [[ $rc == 0 && ${1:-} == --rm-root ]]; then if ! rm -rf -- "$ROOT"; then podman unshare rm -rf -- "$ROOT" || rc=1; fi; fi
exit "$rc"
EOF
chmod 755 "$ROOT/bin/cleanup" "$ROOT"/probe/bin/*.sh; bash -n "$ROOT/bin/lib.sh" && bash -n "$ROOT/bin/cleanup" && echo syntax-ok
```

Expected: `syntax-ok`。ラッパーは観測継続のため0を返す場合がある。各 Step の .rc と Expected を必ず照合し、準備・smoke・設定登録等の前提が失敗したら依存する Step を実行せず not run とする。create/inspect エラーは CLI の失敗と分類しない。

`$ROOT/bin/` 配下 2 本、`probe/bin/` 配下 2 本。

- [ ] **Step 3: 既存イメージを列挙し、必要 CLI が入った ID を明示選択する（ビルドしない）**

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
hrun host-git-version hgit --version
hrun host-versions sh -c 'podman --version; podman info --format "rootless={{.Host.Security.Rootless}}"; id -u'
podman images --format '{{.ID}}\t{{.Repository}}:{{.Tag}}\t{{.CreatedAt}}' | grep 'localhost/' > "$ROOT/logs/images.tsv"; cut -f1,3 "$ROOT/logs/images.tsv"
# Repository 名と Dockerfile の履歴を確認し、既知の claude-container 用イメージを一つ選ぶ。
# 候補全部を実行しない。選択した ID を対話で入力する（秘密ではない）。
# 候補なしならこのブロックの残りを実行せず Step 5 へ進む。
read -r -p '検査する既存イメージ ID: ' candidate_id
[[ $candidate_id =~ ^[0-9a-f]{12,64}$ ]] || { echo 'ID形式不正'; exit 2; }
IMAGE=$(podman image inspect "$candidate_id" --format '{{.Id}}') || exit 1
podman image inspect "$IMAGE" > "$ROOT/logs/image.json"
python3 - "$ROOT/logs/image.json" <<'PYIMAGE'
import json,sys
x=json.load(open(sys.argv[1]))[0]
c=x['Config']
assert c['Entrypoint']==['/usr/bin/setpriv','--ambient-caps=-all','--inh-caps=-all','/usr/bin/tini','--']
assert c.get('User')=='node'
assert not c.get('Volumes'), '暗黙 volume を持つイメージは対象外'
print('IMAGE_STATIC_CHECK_OK')
PYIMAGE
# この確認が非0なら停止し、以降を実行しない。既存imageの秘密の有無を調べて読み出さない。
printf 'IMAGE=%q\n' "$IMAGE" >> "$ROOT/env.sh"
crun versions -t 60 -w "$ROOT/ws-empty" -- sh -c 'set -e; id; head -1 /etc/os-release; git --version; codex --version; claude --version; python3 -c "import tomllib"'

```

Expected: rootless=true、静的確認成功、versions.rc=0、両 CLI と Git の版、tomllib が揃う。選ぶのは製品用にビルドしたと分かる既存イメージで、検証用に秘密を焼き込んだイメージは使わない。由来や設定・自動起動コードを確認できない候補は使わず、準備計画が必要と記録する。版差は明記し、対象版でない機能の結論に転用しない。CLI が足りない場合は別の確認済み候補を別観測名で調べるか、Task 2/3 の image 依存部分を not run とする。新規 pull/build は行わない。

- [ ] **Step 4: smoke（ENTRYPOINT 維持・mount・UID 対応・マーカー書込み経路）**

Step 3 で利用可能な IMAGE を確定できなければこの Step と Task 2/3 は実行せず not run と記録し、Step 5 と Task 4 に進む。IMAGE が設定されていても versions の必須項目が失敗した候補では進まない。

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
podman image inspect "$IMAGE" --format 'image-entrypoint={{json .Config.Entrypoint}} image-cmd={{json .Config.Cmd}}' | tee "$ROOT/logs/image-config.log"
crun smoke -w "$ROOT/ws-empty" -- sh -c 'id; cat /proc/1/comm; /probe/bin/mcp-marker.sh </dev/null; /probe/bin/notify-marker.sh a b; touch /workspace/smoke.txt && echo WS_WRITE_OK'
save_markers smoke || exit 1
ls -ln "$ROOT/probe/out" "$ROOT/ws-empty"; cat "$ROOT/logs/smoke-markers/states" "$ROOT/logs/smoke-markers/"*.log
```

Expected: `image-config.log` の Entrypoint が `["/usr/bin/setpriv","--ambient-caps=-all","--inh-caps=-all","/usr/bin/tini","--"]`、`smoke.inspect` の entrypoint が同一で cmd が `["sh","-c",...]`、`net=none`、binds が `/workspace` と `/probe` の 2 本。`/proc/1/comm` が `tini`。`uid=1000(node)`。ホスト側の出力ファイルの所有 uid が `host-versions.log` の `id -u` と一致。`mcp-started.log` に `cwd=/workspace argc=0`、`notify-fired.log` に `argc=2`、`WS_WRITE_OK`、rc=0。これはマーカーの**書込み経路の対照**であり、CLI が定義を読んで起動する対照ではない。

- [ ] **Step 5: 結果記録の骨組みを作る**

`$RESULTS` を次の見出しで作る。§0 に「製品 entrypoint.sh（firewall・MCP ゲート・秘密配線・cap 剥奪後の実効権限）は本計画では通過していない。境界証明には使わない」を最初から書く。

```markdown
# c3c 第0A段階 調査結果
日付: <実行日>。対象 commit: <hgit -C $CC rev-parse HEAD>。計画: 2026-09-20-c3c-phase0-validation.md。実行: Opus（Podman ホスト）。
## 0. 条件（ホスト版・イメージ ID と版・ENTRYPOINT/CMD の inspect・不通過の明記）
## 1. G2: Git 相対リンクの双方向互換
## 2. G3-A: Codex CLI 表面・設定源・sandbox コマンドの実行経路
## 3. G3-B: 設定登録・TOML 構造・解析不能時の挙動・MCP/notify マーカー観測
## 4. 判定表と 0B 必須の未実測表
## 5. 残留物・後始末・レビュー経過
```

Expected: `hgit -C "$CC" status --short` の増分が `?? docs/superpowers/plans/2026-09-20-c3c-phase0a-results.md` のみ。

---

## Task 2: G2 — 使い捨て repo での Git 相対リンク双方向

**Files:**
- Create: `$ROOT/repo/`（使い捨て）、`$ROOT/wt-sibling/`、`$ROOT/logs/g2-*`
- Modify: `$RESULTS` §1

**Interfaces:**
- Consumes: `hgit`・`crun`・`$IMAGE`。
- Produces: 判定 G2-1（ホスト作成→コンテナ利用）、G2-2（コンテナ作成→ホスト利用）、G2-3（絶対参照の兄弟 worktree の列挙と利用不可診断）、G2-4（両側 Git 版と生の `gitdir` 内容）。

- [ ] **Step 1: 相対リンク対応の有無を両側の help で確認する**

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
hgit -C "$ROOT/repo" init -q -b main || exit 1
hrun g2-host-help hgit -C "$ROOT/repo" worktree add -h
crun g2-ctr-help -w "$ROOT/repo" -- sh -c 'git --version; git -C /workspace worktree add -h 2>&1'
```

Expected: 両ログが usage/options の help に到達していることを先に確認する（help の終了コード129等を通常操作の失敗と混同しない）。not a git repository 等ならオプション不在とせず help 未取得と記録する。ホスト側に `--relative-paths` 行がある（無ければ相対リンク作成は not run とし、実行時に別形式へ自動変更しない）。コンテナ側の有無は実測値を §1 に書く（無ければ Step 4 は絶対リンクの**診断**に切り替わり、G2-2 は「コンテナ側 Git 版では相対作成不可」と記録する。黙って絶対で進めたことにしない）。

- [ ] **Step 2: ホストで repo と相対参照 worktree（repo 配下）を作る**

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
hgit -C "$ROOT/repo" commit -q --allow-empty -m init
printf '.c3c-probe/\n' >> "$ROOT/repo/.git/info/exclude"
hrun g2-host-add hgit -C "$ROOT/repo" worktree add --relative-paths .c3c-probe/wt-host -b probe/host
hrun g2-host-links sh -c "cat '$ROOT/repo/.c3c-probe/wt-host/.git'; echo ---; cat '$ROOT/repo/.git/worktrees/wt-host/gitdir'"
hrun g2-host-list hgit -C "$ROOT/repo" worktree list --porcelain
```

Expected: `g2-host-links.log` の `gitdir:` と back-link が **どちらも相対パス**（逐語で §1 へ）。`worktree list` が 2 件。

- [ ] **Step 3: ホスト作成→コンテナ利用（status・ブランチ・commit・hash 一致）**

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
crun g2-h2c -w "$ROOT/repo" -- sh -c 'set -x; cd /workspace/.c3c-probe/wt-host && git rev-parse --git-common-dir && git branch --show-current && git status --short && echo from-container > from-container.txt && git add from-container.txt && git commit -q -m container-commit && git rev-parse HEAD && git -C /workspace worktree list --porcelain'
hrun g2-h2c-verify hgit -C "$ROOT/repo/.c3c-probe/wt-host" rev-parse HEAD
```

Expected（成立）: rc=0、コンテナ内 `--git-common-dir` を worktree の cwd から解決すると `/workspace/.git`、ブランチ `probe/host`、コンテナ内 `rev-parse HEAD` と `g2-h2c-verify.log` の hash が一致。`worktree list` がコンテナ内パスで 2 件。Expected（不成立）: `fatal:` を引用し G2-1 不成立。修復コマンドを実行しない。

- [ ] **Step 4: コンテナ作成→ホスト利用**

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
crun g2-c2h -w "$ROOT/repo" -- sh -c 'set -ex; cd /workspace; if git worktree add -h 2>&1 | grep -q relative-paths; then echo MODE=relative; git worktree add --relative-paths .c3c-probe/wt-ctr -b probe/ctr; else echo MODE=absolute-diagnostic; git worktree add .c3c-probe/wt-ctr -b probe/ctr; fi; cat .c3c-probe/wt-ctr/.git; echo ---; cat .git/worktrees/wt-ctr/gitdir'
hrun g2-c2h-host sh -c "$(declare -f hgit); cd '$ROOT/repo/.c3c-probe/wt-ctr' && hgit status --short && hgit branch --show-current && echo from-host > from-host.txt && hgit add from-host.txt && hgit commit -q -m host-commit && hgit rev-parse HEAD"
crun g2-c2h-verify -w "$ROOT/repo" -- git -C /workspace/.c3c-probe/wt-ctr rev-parse HEAD
```

Expected: `MODE=relative` かつ両リンクが相対で、ホスト側 commit の hash と `g2-c2h-verify.log` が一致すれば G2-2 成立。`MODE=absolute-diagnostic` の場合はホスト側の `fatal:`（`/workspace/...` を指す）を引用し「相対化にはホスト側作成または版の引き上げが要る」と記録する。

- [ ] **Step 5: 絶対参照の兄弟 worktree の診断と、既存 worktree の読み取り専用列挙**

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
hrun g2-sibling-add hgit -C "$ROOT/repo" worktree add "$ROOT/wt-sibling" -b probe/sibling
hrun g2-sibling-links sh -c "cat '$ROOT/wt-sibling/.git'; echo ---; cat '$ROOT/repo/.git/worktrees/wt-sibling/gitdir'"
crun g2-sibling -w "$ROOT/repo" -- sh -c 'git -C /workspace worktree list --porcelain; p=$(git -C /workspace worktree list --porcelain | sed -n "s/^worktree //p" | grep -E "/wt-sibling$"); echo "outside=$p"; test -d "$p" && echo PRESENT || echo ABSENT_IN_CONTAINER'
# 実 repo の既存 worktree は読み取り専用の件数だけを記録する。
hrun g2-existing hgit -C "$CC" worktree list --porcelain -z
python3 - "$ROOT/logs/g2-existing.log" <<'PYCOUNT'
import sys
x=open(sys.argv[1],'rb').read().split(b'\0')
print('worktree_count='+str(sum(v.startswith(b'worktree ') for v in x)))
PYCOUNT
```

Expected: コンテナ内の `worktree list` に兄弟 worktree が**ホストの絶対パスで列挙**され `ABSENT_IN_CONTAINER`（`prunable` 注記の有無も記録）。これが G2「列挙可能でも mount 外」の実例。`g2-existing.log` は既存 worktree の **件数だけ**を §1 に転記し、パスは書かない。修復・移動・prune をしない。

- [ ] **Step 6: §1 を確定する**

Expected: G2-1〜G2-4 が成立／不成立／not run で並び、根拠ログ名、両側の Git 版、生の `gitdir` 内容が付く。「概ね」等の主語のない表現を使わない。

---

## Task 3: G3 — Codex の CLI 表面・設定源・登録・MCP マーカー・sandbox 経路（秘密なし）

**Files:**
- Create: `$ROOT/logs/codex-*`、`$ROOT/codex-home/config.toml`（Codex 自身に書かせる）、`$ROOT/codex-home-broken/config.toml`
- Modify: `$RESULTS` §2・§3

**Interfaces:**
- Consumes: `crun`・`$IMAGE`・マーカー。
- Produces: 候補オプションの有無表、設定源の表、判定 G3-A1（`mcp add` の保存先と TOML 構造）、G3-A2（解析不能時の挙動）、G3-A3（認証前の MCP/notify 起動有無）、G3-A4（モデル不要 sandbox コマンドの経路と実効）。

- [ ] **Step 1: help を採取し、候補オプションを照合する**

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
for h in "codex --version" "codex --help" "codex exec --help" "codex mcp --help" "codex mcp add --help" "codex sandbox --help" "claude --version" "claude --help"; do
  crun "help-$(echo "$h" | tr ' -' '__')" -t 60 -w "$ROOT/ws-empty" -- $h
done
grep -nE -- '--sandbox|--ask-for-approval|--full-auto|-C,|--cd|--profile|-c,|--config|CODEX_HOME|--skip-git-repo-check|--output-last-message|--permission-profile|--sandbox-state-json|--ignore-user-config|notify|hooks|trust|worktree' "$ROOT"/logs/help-*.log
```

Expected: 対象版に存在する各 help が rc=0（`--network none` で完了＝認証不要）。sandbox 自体が未搭載ならその help と Step 7 を not run にする。help の usage が区切り `--` やプラットフォーム副コマンドを要求する版ならその形式に合わせ、変更を §2 に記録する。grep 結果を「候補 → 有／無（help 行を引用）」で §2 に記録。README の `codex exec --sandbox read-only -C /workspace --skip-git-repo-check` に使う 3 つが `codex exec --help` にあること。`claude --help` の `worktree` 該当行は「会話内移動の候補（0B で実測）」として記録するだけで、有無から機能の存否を断定しない。

- [ ] **Step 2: 設定源を静的に列挙する**

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
crun cfg-paths -w "$ROOT/ws-empty" -- sh -c 'ls -la /etc/codex /home/node/.codex 2>&1; env | grep -i codex; echo HOME=$HOME; true'
```

Expected: §2 の表「設定源／対象版での確認手段／保存先／コンテナから書けるか」を次の行で埋める。(1) `$CODEX_HOME/config.toml`（user）: Step 3 で実測、rw mount 内、書ける。(2) system 層（`/etc/codex` 等）: `cfg-paths.log` の有無、所有者だけで保証せず、mode/実効権限の確認は未実測。(3) 起動引数 `-c`・`--profile`: Step 1 の help。(4) project 側の信頼設定（`projects` テーブル・trusted project 層）: 対話確認が要るため **0B**。(5) plugin・cloud defaults: 公式資料（2026-09-20 事前観測の優先順位 CLI > trusted project > profile > user > cloud defaults > system > builtin）を引用し、対象版での実効は「未確認」と明記。「網羅した」とは書かない。

- [ ] **Step 3: `codex mcp add` で登録させ、保存先と TOML 構造を確認する**

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
crun mcp-add -w "$ROOT/ws-empty" -c "$ROOT/codex-home" -- codex mcp add probe -- /probe/bin/mcp-marker.sh
crun mcp-list -w "$ROOT/ws-empty" -c "$ROOT/codex-home" -- codex mcp list
find "$ROOT/codex-home" -type f | sort; cat "$ROOT/codex-home/config.toml"
crun toml-check -c "$ROOT/codex-home" -w "$ROOT/ws-empty" -- python3 -c 'import tomllib,json; d=tomllib.load(open("/home/node/.codex/config.toml","rb")); print(json.dumps(d,indent=1)); assert d["mcp_servers"]["probe"]["command"]=="/probe/bin/mcp-marker.sh"'
```

Expected（成立）: `mcp-add` rc=0、`toml-check` rc=0（`mcp_servers.probe.command` が一致）、`mcp list` に `probe`。テーブル名・キー名を逐語で §3 に写す。Expected（不成立）: `add` が認証・通信を要求して失敗したら文言を引用し、`[mcp_servers.probe]\ncommand = "/probe/bin/mcp-marker.sh"` を手書きして 同じコマンドの観測名を `mcp-list-manual`・`toml-check-manual` に変えて再実行し「手書き」と記録する。後続の登録成功の前提は manual 側の両 .rc=0 と内容を参照する。手書きでも不成立なら Step 4〜6 は not run（sandbox 調査は MCP を含まない別の空設定ホームで独立に行う）。

- [ ] **Step 4: notify をルートに置き、構造を確認する**

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
{ printf 'notify = ["/probe/bin/notify-marker.sh"]\n'; cat "$ROOT/codex-home/config.toml"; } > "$ROOT/codex-home/config.new" && mv "$ROOT/codex-home/config.new" "$ROOT/codex-home/config.toml"
crun toml-check2 -c "$ROOT/codex-home" -w "$ROOT/ws-empty" -- python3 -c 'import tomllib; d=tomllib.load(open("/home/node/.codex/config.toml","rb")); assert d["notify"]==["/probe/bin/notify-marker.sh"] and "probe" in d["mcp_servers"]; print("root-notify-ok")'
crun mcp-list2 -w "$ROOT/ws-empty" -c "$ROOT/codex-home" -- codex mcp list
```

Expected: `root-notify-ok`（末尾追記だとテーブル内キーになるため先頭に置く）。`mcp-list2` が Step 3 と同じ一覧（notify 追加で読めなくならない）。

- [ ] **Step 5: 解析不能な設定での挙動（無害な壊れた TOML）**

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
cp "$ROOT/codex-home/config.toml" "$ROOT/codex-home-broken/config.toml"; printf '\n[mcp_servers.broken\ncommand = 1\n' >> "$ROOT/codex-home-broken/config.toml"
crun mcp-list-broken -w "$ROOT/ws-empty" -c "$ROOT/codex-home-broken" -- codex mcp list
```

Expected: rc≠0 かつ解析エラーの文言があれば「この操作では解析不能で停止」。rc=0 で一覧が出れば「解析不能を黙って無視する経路あり」として G3 の懸念に記録。いずれも `codex exec` 経路の挙動は 0B で別途確認する。

- [ ] **Step 6: 認証なしで `codex exec` を起動し、MCP・notify マーカーを観測する**

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
save_markers pre-exec || exit 1
: > "$ROOT/probe/out/mcp-started.log"; : > "$ROOT/probe/out/notify-fired.log"
crun exec-noauth -t 150 -w "$ROOT/ws-empty" -c "$ROOT/codex-home" -- timeout 120 codex exec --sandbox read-only -C /workspace --skip-git-repo-check "Reply with exactly the single word: pong"
save_markers exec-noauth || exit 1
cat "$ROOT/logs/exec-noauth-markers/states" "$ROOT/logs/exec-noauth-markers/"*.log
find "$ROOT/codex-home" -newer "$ROOT/env.sh" -type f | sort > "$ROOT/logs/exec-noauth-files.log"
```

Expected: `pre-exec-markers/states` と smoke 保存分からの差分を §3 に記録する。pre-exec は累積記録なので、中間操作での追記があっても add/list/broken のどれで起動したかは断定しない。cleanup は最終 `probe/out` も退避し、途中終了時と Step 6 スキップ時の証拠を残す。`pong` は返らない（認証なし・`--network none`）。失敗文言と rc を引用。判定 G3-A3 は次の 2 値のみ。**マーカー行あり** → 「認証・通信より前に stdio サーバーが起動する（`cwd=` を記録）」。**マーカー行なし** → 「未到達。認証失敗で起動前に終了した可能性と起動しない仕様を区別できない。実認証での対照（0B）が必須」。**未起動を保護成功と書かない**。notify も同様。`codex-home/` の増分ファイルを列挙する。

- [ ] **Step 7: モデル不要の sandbox コマンドの実行経路（対照付き）**

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
# help にsandboxの -c/--config と -C/--cd があることを先に確認する。
# 下記は現在の config reference にある sandbox_mode の候補を明示比較する。
crun sb-pc -w "$ROOT/ws-sb" -- sh -c 'echo hi > /workspace/pc.txt && echo PC_WRITTEN'
crun sb-ro -t 90 -w "$ROOT/ws-sb" -c "$ROOT/codex-home-sandbox" -- codex sandbox -c 'sandbox_mode="read-only"' -C /workspace sh -c 'echo INNER_BEGIN; if echo hi > /workspace/sb-ro.txt; then echo WRITE_OK; else rc=$?; echo "WRITE_DENIED rc=$rc"; exit "$rc"; fi'
crun sb-ww -t 90 -w "$ROOT/ws-sb" -c "$ROOT/codex-home-sandbox" -- codex sandbox -c 'sandbox_mode="workspace-write"' -C /workspace sh -c 'echo INNER_BEGIN; echo hi > /workspace/sb-ww.txt && echo WRITE_OK'
ls -l "$ROOT/ws-sb"
```

Expected: 素の対照は PC_WRITTEN と pc.txt。sandbox 側は INNER_BEGIN により内部コマンド到達を判定する。設定非対応・sandbox自体の起動失敗・内部未到達は not run とし保護成功にしない。read-only 候補は内部到達＋OS拒否＋sb-ro.txt不在、workspace-write候補は内部到達＋WRITE_OK＋sb-ww.txt存在を照合する。ただし実効設定の適用を対象版の資料/診断で確認できない場合は「設定適用未確認」とし、候補別の強制力を確定しない。本物の entrypoint.sh 経路とモデル経由の拒否確認は、どの結果でも0Bに残る。

- [ ] **Step 8: §2・§3 を確定する**

Expected: 候補オプション表、設定源表、G3-A1〜A4 の判定と根拠ログ名。信頼記録の保存先・偽造可否、hook trust の対話／再開／非対話、モデル経由の sandbox 実効は「0B 必須」と明記する。

---

## Task 4: 判定・未実測表・後始末・レビュー

**Files:**
- Modify: `$RESULTS` §4・§5
- Delete: `$ROOT/ledger.tsv` に記録したコンテナのみ（`--rm-root` 時に `$ROOT`）。イメージ・既存 worktree・台帳は削除しない

**Interfaces:**
- Consumes: §1〜§3 の判定。
- Produces: 「0A で確定した事実」「0B 必須の未実測表」「止めて持ち主へ戻す条件の該当」「G1/G4 への事実の引き継ぎ」。

- [ ] **Step 1: 判定表と 0B 必須の未実測表を書く**

`$RESULTS` §4 に 2 表を書く。表 A は G2-1〜G2-4・G3-A1〜A4 の成立／不成立／not run（理由）と根拠ログ名。表 B（0B 必須・本計画では未実測）は次を全行「not run」で載せ、0A 完了で消さない。

| 項目 | 仕様根拠 | 0B での前提 |
|---|---|---|
| 実認証での MCP 起動時期（起動直後／最初のターン）と承認済み定義の起動対照 | G3 | 使い捨て `CODEX_DIR`・限定認証・製品 firewall 経由 |
| 信頼記録（`projects` 等）の保存先とコンテナからの偽造可否 | G3 | 対話起動（TTY） |
| モデル経由の `--sandbox read-only` 実効（ツール呼出しイベント + OS 拒否） | G3 | 実認証 |
| hook/notify の発火（対話・再開・非対話）と hook trust | G3 | 実認証 |
| 変更済み・未承認・解析不能な定義の実行前停止（会話内再読込） | G3・§7 | 実認証 |
| 両 CLI の同一会話内 worktree 移動（A→B、B 変更後の再移動、判定失敗） | §7 | 使い捨て repo・無害定義・実認証 |
| 製品 entrypoint 経由の firewall・cap 剥奪・`:ro` 保護・ホスト `~/.codex` 不変 | §9 | 実コンテナ |

止める条件（該当すれば「持ち主判断待ち」）: 同じプローブを 2 回実行して観測が食い違う／`$ROOT`・台帳外に残留物／禁止命令を使わないと進められない Step があった。

Expected: 「0A 完了は G3 完了・製品実装許可ではない。第1・第3段階の詳細計画は 0B の結果を待つ」の 1 文が §4 末尾にある。

- [ ] **Step 2: G1/G4 への事実の引き継ぎ（設計はしない）**

Expected: §4 に、両側の `git rev-parse --git-common-dir` の値、絶対参照 worktree の列挙結果（G1 へ）、`codex-home/` の増分ファイル一覧と `mcp add` の保存先（G4 へ）を引用のみで書く。「〜すべき」の文が無い。

- [ ] **Step 3: 後始末と残留確認（自分の資源に限る）**

```bash
source "${ROOT:?}/env.sh"; source "$ROOT/bin/lib.sh"
"$ROOT/bin/cleanup"; echo "cleanup rc=$?"; cat "$ROOT/logs/rm-failed" 2>/dev/null
podman ps -a --filter "label=c3c.phase0.owner=$RUN_ID" --format '{{.ID}}'
if [[ -n ${IMAGE:-} ]]; then podman image exists "$IMAGE" && echo image-kept; else echo "image-check: not run（未選択）"; fi
hgit -C "$CC" status --short; hgit -C "$CC" worktree list --porcelain | grep -c '^worktree '
```

Expected: cleanup rc=0、`rm-failed` なし、`$RUN_ID` のコンテナ 0 件、選択済みなら `image-kept`（イメージは削除しない）。未選択なら image-check は not run。`hgit status` の増分が `$RESULTS` のみ、既存 worktree 件数が Task 2 Step 5 と同じ。ホスト設定は内容・statともに参照しない。並行セッションによる変更を今回の副作用と断定しない。自分の変更範囲とmount/資源IDの記録で範囲を照合する。退避に成功して残留がなければ `"$ROOT/bin/cleanup" --rm-root` で `$ROOT` を消す。退避失敗時は `$ROOT` を残して報告する。§5 に残留物と退避先の RUN_ID（パスは書かない）を記録する。

- [ ] **Step 4: レビュー（Critical・Important 0 件まで、最大 5 巡）**

- 対象: `$RESULTS` 全文と本計画。レビュアーは仕様 §9 の Codex 標準レビュー（持ち主環境の通常運用。`$ROOT`・実験 config は渡さない）と Fable の読み取り専用レビュー。観点: 未実測の成功扱い、根拠ログの有無、後始末の範囲、0B 必須項目の消失、ホスト固有パス・Repository 名の混入。
- 各巡で Critical・Important は根拠確認→修正→確認限定巡で 0 件にする。却下は根拠を §5 に残す。
- 同型の指摘が 2 巡続いたら修正を止め、別の Codex セッションに「文脈不足／前提の誤り（再プローブ要）／見解の相違」の診断だけを依頼して §5 に書く。前提の誤りなら該当 Task を再実行、見解の相違なら持ち主へ戻す。
- 5 巡で残件があれば確定せず、残件と次の判断を報告する。commit・push・タグは行わない。

Expected: §5 に巡ごとの件数と対応、最終状態「Critical 0・Important 0」または「残件あり（持ち主判断待ち）」。

---

## セルフレビュー（作成時）

- 依存順: Task 1 Step 1（ROOT・env.sh）→ Step 2（lib.sh・cleanup・マーカー）→ Step 3（IMAGE 選択、`IMAGE=$id crun` は lib.sh 定義後）→ Step 4（smoke は IMAGE 確定後）→ Task 2/3（`crun` と `$IMAGE` に依存、順不同可）→ Task 4。`hgit` は `env -i` 子プロセス内だけで HOME を差し替え、`hrun` 内から使う箇所は `declare -f hgit` で関数を渡す。
- 秘密なしの担保: `crun` の mount は `/workspace`・`/probe`・任意の `/home/node/.codex`（`$ROOT` 内の空ディレクトリ）の 3 本のみで、ホスト env を渡さない。ホストで codex/claude を起動しない。ホスト設定のstatによる比較も行わない。
- 仕様 G2: 版（Task 2 Step 1）、双方向と hash 一致（Step 3・4）、兄弟 worktree の列挙のみ（Step 5）。G3: 設定源（Task 3 Step 2）、登録と構造（Step 3・4）、解析不能（Step 5）、起動有無（Step 6）、sandbox 経路（Step 7）。実認証・信頼記録・hook trust・会話内移動・製品境界は Task 4 表 B に残し、0A 完了と切り離した。
- self-review1 の Important 1〜3・10 と Codex 指摘の重複 mount・TOML ルート・後始末・Git 隔離・匿名化は Task 1・3・4 で対応した。4〜9 は 0B の範囲として表 B に移した。
- 既知の限界: `codex sandbox` の実効設定の適用と `mcp add` の書式は対象版の help/資料に依存し、成立しなければ not run になる。IMAGE 候補が無い場合は Task 2・3 の全 Step が not run で、準備計画の要否を報告する。

---

**実装: Opus** — 既存イメージの選択・rootless Podman での実測・観測結果の解釈が第0B段階と第1/第3段階の安全性判断の入力になるため（仕様 §11 末尾と同じ判定）。Fable は本計画の作成とレビューを担当し、実験を実行しない。

**実行方式の推奨: `superpowers:executing-plans` で、Podman を使えるホスト側の同一 Opus セッションが Task 1〜4 を順に実行する。** 理由: 全 Task が Task 1 の `$ROOT`・`$IMAGE`・helper と同じ shell 環境を前提にしており、サブエージェント分割は `env.sh` の引き継ぎ漏れと既存資源への誤操作の余地を増やす一方、レビューは Task 4 で独立に行うため分割の利点が小さい。
