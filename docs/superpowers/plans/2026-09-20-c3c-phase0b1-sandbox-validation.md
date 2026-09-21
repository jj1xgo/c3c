# c3c 第0B-1段階: 組み込み permission profile の秘密なし追試

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 第0Aで引数エラーになった sandbox 検証を、公式に記載された組み込み profile と対象 CLI の書式で追試し、内部到達と OS の書込み制御を区別して記録する。

**Architecture:** 同じ既存イメージを、秘密なし・`--network none` の使い捨てコンテナで使用する。対照・read-only・workspace は同じ3マウントと uid で比較する。Codex のモデルや認証を使用せず、製品 ENTRYPOINT を維持し CMD のみ差し替える。製品 `entrypoint.sh` の境界証明ではない。

**Tech Stack:** rootless Podman、codex-cli 0.155.1、Python 3、Bash。

**Spec:** [段階仕様](../specs/2026-09-20-c3c-incremental-design.md) G3、[第0A結果](2026-09-20-c3c-phase0a-results.md) G3-A4。

## Global Constraints

- 持ち主の「暫くは Codex だけで進めて」（2026-09-20）に従い、作成・実行・独立レビューを Codex で行う。Claude を起動しない。
- 製品ファイル、既存 worktree、ホスト設定・認証を変更・共有・参照しない。build/pull/prune、cap追加、seccomp緩和、full-accessへの切替をしない。
- 対象は前回と同じ image ID。存在・静的前提・版のいずれかが不一致なら実行を止める。別イメージへの無言切替なし。
- モデル応答・実認証・MCP/hook trust・同会話移動・製品 firewall は対象外。第0A 表Bの未実測を消さない。
- repo の変更は本計画と結果 Markdown のみ。自動commit/pushなし。TDDではなく観測。結果と終了コードを保存し、失敗を成功へ分類しない。

## 根拠と対象版との差

[公式 Permissions](https://learn.chatgpt.com/docs/permissions) を2026-09-20に確認。`:read-only` と `:workspace` は組み込み値である。旧 sandbox 設定と profile は混在させず、本追試は空の専用 config と `--permission-profile` のみを使う。

[公式の sandbox 説明](https://learn.chatgpt.com/docs/agent-approvals-security) は Linux の bwrap/seccomp とコンテナによる制約を説明している。ただし CLI 例のプラットフォーム副コマンド・引数名は0.155.1の実測helpと異なる。本追試は実測した `codex sandbox --permission-profile NAME -C DIR COMMAND...` を使い、公式例をそのまま転用しない。

## Review Focus

1. profile の不明値や引数エラーをOS拒否と誤認しない: `INNER_BEGIN`、rc、errno、ファイル状態を照合。
2. 素の書込み対照を同じworkspace・probe・空Codex home mount、uidで実施する。
3. 新旧設定を混在させない: 専用 `config.toml` は空。`sandbox_mode` は渡さない。
4. namespace等の起動失敗では権限を広げず未到達として残す。
5. cleanupと実行時stdoutを保存してからROOTを削除する。

## Task 1: 既存 helper から追試 runner を構築し静的検査する

**Files:** 一時領域 `/tmp/c3c-phase0b1/` に `build-runner.py`、`run.sh`。前計画は読取りのみ。
**Interfaces:** 前計画の先頭2個の Bash ブロック（使い捨て基盤）を SHA256 で固定し再利用。`crun`・`cleanup` の契約は前計画と同じ。ROOTのprefixはhelper互換のため`c3c-0a`を維持するが、前回と異なるmktemp領域を作る。

- [ ] 次の Python を `build-runner.py` として保存し、repo rootで実行する。

```python
from pathlib import Path
import hashlib,re
cc=Path.cwd()
p=cc/'docs/superpowers/plans/2026-09-20-c3c-phase0-validation.md'
s=p.read_text()
assert hashlib.sha256(p.read_bytes()).hexdigest()=='f8f34030218530a8153b156331c027ba224fb4977b01e27fd4587651fa45f6a3'
blocks=re.findall(r'```bash\n(.*?)\n```',s,re.S)
setup='\n'.join(blocks[:2])
body=r'''
# 保留した各実測の終了コードはcrunが保存する。準備失敗はset -eで止める。
source "$ROOT/env.sh"; source "$ROOT/bin/lib.sh"
printf '%s\n' "$ROOT" > /tmp/c3c-phase0b1/root-path
printf '%s\n' "$RUN_ID" > /tmp/c3c-phase0b1/run-id
finish() {
  local rc=$? cleanup_rc=0
  trap - EXIT
  "$ROOT/bin/cleanup" > /tmp/c3c-phase0b1/cleanup.log 2>&1 || cleanup_rc=$?
  printf '%s\n' "$rc" > /tmp/c3c-phase0b1/run.rc
  printf '%s\n' "$cleanup_rc" > /tmp/c3c-phase0b1/cleanup.rc
  if [[ $cleanup_rc != 0 ]]; then exit "$cleanup_rc"; fi
  exit "$rc"
}
trap finish EXIT
IMAGE=28b724cd6363a9bdbc4f0a44386bdd6b7dc18d0c8fd7142ca219a83c277cc05c
printf 'IMAGE=%q\n' "$IMAGE" >> "$ROOT/env.sh"
podman image inspect "$IMAGE" > "$ROOT/logs/image.json"
python3 - "$ROOT/logs/image.json" <<'PYCHECK'
import json,sys
c=json.load(open(sys.argv[1]))[0]['Config']
assert c['Entrypoint']==['/usr/bin/setpriv','--ambient-caps=-all','--inh-caps=-all','/usr/bin/tini','--']
assert c.get('User')=='node' and not c.get('Volumes')
print('IMAGE_STATIC_CHECK_OK')
PYCHECK
podman info --format '{{.Host.Security.Rootless}}' > "$ROOT/logs/rootless.log"
[[ $(cat "$ROOT/logs/rootless.log") == true ]]
: > "$ROOT/codex-home-sandbox/config.toml"
crun profile-preflight -w "$ROOT/ws-sb" -c "$ROOT/codex-home-sandbox" -- sh -c 'set -eu; codex --version; codex sandbox --help; id; cat /proc/1/comm'
[[ $(cat "$ROOT/logs/profile-preflight.rc") == 0 ]]
grep -qx 'codex-cli 0.155.1' "$ROOT/logs/profile-preflight.log"
grep -q -- '--permission-profile' "$ROOT/logs/profile-preflight.log"
cat > "$ROOT/probe/write-check.py" <<'PYPROBE'
import errno,json,os,sys
from pathlib import Path
print('INNER_BEGIN',flush=True)
print(json.dumps({'uid':os.getuid(),'gid':os.getgid(),'cwd':os.getcwd()}),flush=True)
p=Path('/workspace')/sys.argv[1]
try:
    with p.open('x') as f:
        f.write('c3c-profile-probe\n')
except OSError as e:
    print(f'OS_ERROR errno={e.errno}',flush=True)
    if e.errno in (errno.EACCES,errno.EROFS):
        print('WRITE_DENIED',flush=True)
        sys.exit(42)
    sys.exit(43)
print('WRITE_OK',flush=True)
PYPROBE
cp "$ROOT/probe/write-check.py" "$ROOT/logs/write-check.py"
crun profile-control -w "$ROOT/ws-sb" -c "$ROOT/codex-home-sandbox" -- python3 /probe/write-check.py control.txt
[[ $(cat "$ROOT/logs/profile-control.rc") == 0 && -f $ROOT/ws-sb/control.txt ]]
grep -qx WRITE_OK "$ROOT/logs/profile-control.log"
crun profile-ro -w "$ROOT/ws-sb" -c "$ROOT/codex-home-sandbox" -- codex sandbox --permission-profile :read-only -C /workspace python3 /probe/write-check.py ro.txt
crun profile-workspace -w "$ROOT/ws-sb" -c "$ROOT/codex-home-sandbox" -- codex sandbox --permission-profile :workspace -C /workspace python3 /probe/write-check.py workspace.txt
python3 - "$ROOT" <<'PYRESULT'
import json,sys
from pathlib import Path
r=Path(sys.argv[1]); result={}
for name,f in [('profile-control','control.txt'),('profile-ro','ro.txt'),('profile-workspace','workspace.txt')]:
    rc=(r/'logs'/f'{name}.rc').read_text().strip()
    out=(r/'logs'/f'{name}.log').read_text()
    exists=(r/'ws-sb'/f).exists()
    reached='INNER_BEGIN\n' in out
    if not reached:
        verdict='not run: inner command not reached'
    elif name=='profile-ro':
        verdict='成立' if rc=='42' and 'WRITE_DENIED\n' in out and not exists else '不成立'
    else:
        verdict='成立' if rc=='0' and 'WRITE_OK\n' in out and exists else '不成立'
    result[name]={'rc':rc,'inner_reached':reached,'file_exists':exists,'verdict':verdict}
(r/'logs/profile-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
PYRESULT
# 全マウントと設定ファイルをログへ保存。ホスト実設定は参照しない。
cp "$ROOT/codex-home-sandbox/config.toml" "$ROOT/logs/config-used.toml"
'''
out=Path('/tmp/c3c-phase0b1/run.sh')
out.write_text('#!/bin/bash\nset -Eeuo pipefail\n'+setup+'\n'+body)
print(out)

```

- [ ] `python3 /tmp/c3c-phase0b1/build-runner.py`、`bash -n /tmp/c3c-phase0b1/run.sh` を実行する。

Expected: SHA一致、runner生成、構文成功。準備スクリプトの失敗時にプローブを起動しない。実行前に本計画と生成runnerを独立Codexレビューへ渡し、Critical/Importantを解消する。

## Task 2: 通信・認証なしで追試する

**Files:** 新しい `$ROOT` と台帳、`$ROOT/logs/profile-*`、`/tmp/c3c-phase0b1/run.log`、`run.rc`、`cleanup.rc`。
**Interfaces:** `profile-control` → 対照が成功した場合のみ `profile-ro`・`profile-workspace`。上位runner終了コードと観測ごとのrcを区別する。

- [ ] `bash /tmp/c3c-phase0b1/run.sh > /tmp/c3c-phase0b1/run.log 2>&1` を実行する。
- [ ] `run.rc`・`cleanup.rc`、`profile-results.json`、3本の`.log`/`.rc`/`.inspect`を照合する。

Expected: 対照rc0・INNER_BEGIN・WRITE_OK・control.txtあり。read-onlyは内部到達・errno13/30・rc42・ro.txtなし、workspaceは内部到達・rc0・WRITE_OK・workspace.txtありなら成立。内部未到達はnot run、到達後に期待と異なる場合は不成立。全inspectでnet=none・ENTRYPOINT同一・同じ3mount。image静的検査・版検査・対照に失敗したら依存プローブはnot run。

## Task 3: 保存・残留確認・報告

**Files:** `docs/superpowers/plans/2026-09-20-c3c-phase0b1-results.md`、既存のprivate退避先 `$CC/.claude/test-results/$RUN_ID/`。
**Interfaces:** EXIT時cleanupはコンテナだけを回収してログを退避し、ROOTは保持する。

- [ ] 終了後の `run.log`・`cleanup.log`・runnerと生成元をprivate退避先にコピーし、元と `cmp` で照合する。ファイル名は `run.log`・`cleanup.log`・`run.sh`・`build-runner.py` とする。
- [ ] `podman ps -a --filter "label=c3c.phase0.owner=$RUN_ID" --format '{{.ID}}'` のrc0/空と `podman image exists "$IMAGE"` のrc0を記録する。
- [ ] 退避成功・残留0件なら `$ROOT/bin/cleanup --rm-root` を実行し、rcとROOT不在を外側の記録へ保存する。失敗ならROOTを残し報告する。関係ない資源は削除しない。
- [ ] 結果には対象commit・image ID・版・各rc/内部到達/errno/ファイル状態・根拠ログ・not run理由・後始末を書く。host固有パスを匿名化する。第0A結果は履歴として維持する。
- [ ] `./lint.sh` と独立Codexレビューで結果を確認し、Critical/Importantを解消する。

Expected: 追試の結果が全項目記録され、秘密・通信・capabilityを増やしていない。成功しても通常entrypoint経路、モデル経由の強制力、MCP承認、同会話移動は未実測。起動失敗なら原因を残して次の設計判断へ渡し、自動的に別方式へ切り替えない。

## セルフレビュー

- G3-A4の引数エラーだけを対象にし、G3全体の達成条件を縮めていない。
- profile名は公式、CLI書式は対象版help。旧 `sandbox_mode` は混ぜない。
- helperはレビュー済みの前計画からSHA固定で抽出。今回は全ケース同じ3mount。
- stdoutと後始末の証拠を退避してから削除する。独立レビューは計画と結果の2箇所で実施する。

実装: Codex — 持ち主の一時的なCodex限定指示に従う。認証を扱わない、逐語手順とExpectedを固定した追試であり、実行方式は `superpowers:executing-plans`。

別セッションへ渡す場合の `/goal` 文面: 「第0B-1計画の秘密なしsandbox追試を実行し、結果と証拠を保存、独立CodexレビューのCritical/Importantを解消する。Claude・実認証・製品実装・権限緩和・commit/pushは行わない。」

実行環境: hostのworkspace-write。Podmanはホスト資源へアクセスするため必要なコマンドだけsandbox外実行の承認を使う。プローブ通信は `--network none` 固定。文書調査と独立レビューの通信は実験とは別に扱う。
