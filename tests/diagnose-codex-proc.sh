#!/bin/bash
# #140: ホストの既存イメージで /proc と Codex の失敗経路を採取する。
# 製品の ENTRYPOINT を通さない切り分け用。通常起動の受入検証ではない。
set -euo pipefail

if [[ $# != 1 || -z $1 || $1 == -* ]]; then
  echo "使い方: bash tests/diagnose-codex-proc.sh <ローカルイメージ>" >&2
  exit 2
fi
if ! command -v podman >/dev/null 2>&1; then
  echo "ERROR: Podman のあるホストで実行してください。" >&2
  exit 2
fi

podman --remote=false --version
uname -r
# 名前の付け替え中でも同じイメージを使う。pull・build は行わない。
probe_image=$(podman --remote=false image inspect --format '{{.Id}}' "$1")
printf 'image ID: %s\n' "$probe_image"
for probe_mode in system bundled; do
printf '\n=== bwrap 選択: %s ===\n' "$probe_mode"
# 変更は --rm の書込み層だけ。元イメージ・稼働コンテナには触れない。
# 両ケースで同じ root 初期化→uid 1000 の経路を使う。
podman --remote=false run --rm --pull=never --network=none \
  --userns=keep-id --user=0:0 --workdir=/tmp \
  --env HOME=/home/node --env XDG_CONFIG_HOME=/home/node/.config \
  --env CODEX_HOME=/home/node/.c3c-proc-probe-home \
  --entrypoint /bin/bash -i "$probe_image" -ceu '
    if [[ $1 == bundled ]]; then
      test ! -e /usr/bin/bwrap.c3c-probe-disabled
      mv /usr/bin/bwrap /usr/bin/bwrap.c3c-probe-disabled
    fi
    exec /usr/bin/setpriv --reuid=1000 --regid=1000 --init-groups \
      --inh-caps=-all --ambient-caps=-all /bin/bash -s
  ' c3c-proc-probe "$probe_mode" <<'PROBE'
set -eu
probe() {
  printf '\n--- %s ---\n' "$1"
  shift
  local rc=0
  printf '実行:'
  printf ' %q' "$@"
  printf '\n'
  "$@" || rc=$?
  printf '終了コード: %s\n' "$rc"
}

mkdir -p "$CODEX_HOME" /tmp/c3c-proc-probe-repo
probe '実 Codex 版' codex --version
if command -v bwrap >/dev/null 2>&1; then
probe 'システム bubblewrap 版' /usr/bin/bwrap --version
else
  echo 'PATH にシステム bwrap なし。同梱版の選択を検証します。'
fi
probe 'プロセスの権限' /bin/grep -E '^(Cap|Seccomp|NoNewPrivs)' /proc/self/status
probe '/proc のマウント構成' /bin/grep -E ' /proc(/| )' /proc/self/mountinfo
if [[ -x /usr/bin/bwrap ]]; then
probe 'bwrap: 新規 /proc あり' /usr/bin/bwrap \
  --unshare-user --unshare-pid --ro-bind / / --proc /proc /bin/echo OK
probe 'bwrap: 既存 /proc を継承' /usr/bin/bwrap \
  --unshare-user --unshare-pid --ro-bind / / /bin/echo OK
fi

# API・モデル・認証を使わず、Codex 自身のサンドボックス実行経路を通す。
cd /tmp/c3c-proc-probe-repo
git init -q
probe 'Codex read-only: pwd' codex sandbox \
  -c 'sandbox_mode="read-only"' -- /bin/pwd
probe 'Codex workspace-write: git status' codex sandbox \
  -c 'sandbox_mode="workspace-write"' -- git status --short --branch
printf '\n診断採取完了。各終了コードを確認してください。通常の c3c 起動検証: not run\n'
PROBE
done
