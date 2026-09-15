#!/bin/bash
# 実ビルド・マウント保護・通常 entrypoint の権限と IPv4 通信を検証する。
# --image <ビルド済みイメージ> は検査の反復用。この場合ビルドは明示的に not run。
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
run_id="claude-runtime-$(date +%s)-$$"
mount_project="$run_id-mounts"
results="${RUNTIME_RESULTS_DIR:-$SCRIPT_DIR/.claude/test-results/$run_id}"
started=$SECONDS
image="localhost/$run_id"
build=1
if [[ "$#" == 2 && "$1" == --image ]]; then
  image="$2"
  build=0
elif [[ "$#" != 0 ]]; then
  echo "使い方: $0 [--image <ビルド済みイメージ>]" >&2
  exit 2
fi
mkdir -p "$results"
results="$(cd "$results" && pwd)"

phases=(environment build mounts control-before protected control-after)
declare -A outcome
for phase in "${phases[@]}"; do outcome[$phase]='not run（未到達）'; done
phase=environment
root=""
compose=()
clean_env=(env -i "HOME=$HOME" "PATH=$PATH" "TMPDIR=/tmp"
  "PODMAN_COMPOSE_PROVIDER=${PODMAN_COMPOSE_PROVIDER:-podman-compose}")
if [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then clean_env+=("XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"); fi

# shellcheck disable=SC2329 # EXIT trap から間接的に呼び出す。
finish() {
  local rc=$? cleanup_rc=0 ids network
  trap - EXIT
  set +e
  if [[ "$rc" != 0 && "${outcome[$phase]}" == running ]]; then
    if [[ "$rc" == 77 ]]; then outcome[$phase]='not run（環境の前提を満たさない）'
    else outcome[$phase]="FAIL（終了コード $rc）"; fi
  fi
  if [[ -n "$root" ]]; then
    # この実行が作ったコンテナとネットワークだけを除去する。prune は使わない。
    for name in "$run_id-control-before" "$run_id-protected" "$run_id-control-after"; do
      if podman container exists "$name"; then timeout 20s podman rm -f "$name" || cleanup_rc=1; fi
    done
    # mounts が途中でタイムアウトした場合も、専用の project label で限定して清掃する。
    if ids=$(timeout 20s podman ps -aq --filter "label=io.podman.compose.project=$mount_project"); then
      while IFS= read -r name; do
        [[ -z "$name" ]] || timeout 20s podman rm -f "$name" || cleanup_rc=1
      done <<< "$ids"
    else
      cleanup_rc=1
    fi
    for network in "${run_id}_default" "${mount_project}_default"; do
      if podman network exists "$network"; then timeout 20s podman network rm "$network" || cleanup_rc=1; fi
    done
    if podman image exists "localhost/${mount_project}_claude-auth-workspace:latest"; then
      timeout 20s podman rmi "localhost/${mount_project}_claude-auth-workspace:latest" || cleanup_rc=1
    fi
    if [[ "$build" == 1 ]] && podman image exists "$image"; then
      timeout 20s podman rmi "$image" || cleanup_rc=1
    fi
    rm -rf -- "$root"
  fi
  if [[ "$rc" == 0 && "$cleanup_rc" != 0 ]]; then rc=1; fi
  {
    printf '# 実コンテナ検証\n\n'
    # shellcheck disable=SC2016 # Markdown のバッククォートはリテラル。
    printf -- '- 対象 commit: `%s`\n' "$(git -C "$SCRIPT_DIR" rev-parse HEAD)"
    printf -- '- 終了コード: %s\n- 所要時間: %s 秒\n' "$rc" "$((SECONDS - started))"
    printf -- '- 後始末の終了コード: %s\n\n' "$cleanup_rc"
    printf '| 段階 | 結果 |\n|---|---|\n'
    for name in "${phases[@]}"; do printf '| %s | %s |\n' "$name" "${outcome[$name]}"; done
    printf '| IPv6 | not run（この検証は既定の IPv4 構成。IPv6 対応 runner は別途必要） |\n'
  } > "$results/summary.md"
  cat "$results/summary.md"
  exit "$rc"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

run_phase() {
  phase="$1"; shift
  outcome[$phase]=running
  printf '\n## %s の検査\n' "$phase"
  local rc=0
  timeout --signal=TERM --kill-after=30s "$@" 2>&1 | tee "$results/$phase.log" || rc=$?
  if [[ "$rc" != 0 ]]; then
    if [[ "$rc" == 77 ]]; then outcome[$phase]='not run（環境の前提を満たさない）'
    else outcome[$phase]="FAIL（終了コード $rc）"; fi
    return "$rc"
  fi
  outcome[$phase]=PASS
}

outcome[environment]=running
environment_rc=0
(
  # exit の際に親の EXIT trap をリダイレクト内で動かさない。
  trap - EXIT
  printf '対象 commit: %s\n' "$(git -C "$SCRIPT_DIR" rev-parse HEAD)"
  git -C "$SCRIPT_DIR" status --short
  uname -srmo
  id
  for command in podman python3 curl jq timeout; do
    command -v "$command" || { echo "not run: 必要なコマンド $command がありません"; exit 77; }
  done
  timeout 30s "${clean_env[@]}" podman info || exit 77
  timeout 10s "${clean_env[@]}" podman compose version || exit 77
  # 実マウント検査に必要な --in-pod は podman-compose のオプション。
  provider_help=$(timeout 10s "${clean_env[@]}" "${PODMAN_COMPOSE_PROVIDER:-podman-compose}" --help) || exit 77
  grep -q -- --in-pod <<< "$provider_help" || { echo 'not run: provider に --in-pod がありません'; exit 77; }
  [[ "$(timeout 10s podman info --format '{{.Host.Security.Rootless}}')" == true ]] || { echo 'not run: rootless Podman が必要です'; exit 77; }
) > "$results/environment.log" 2>&1 || environment_rc=$?
cat "$results/environment.log"
if [[ "$environment_rc" != 0 ]]; then exit "$environment_rc"; fi
outcome[environment]=PASS

root="$(mktemp -d /tmp/claude-runtime.XXXXXX)"
mkdir -p "$root/config/.claude" "$root/project" "$root/probe/bin" "$root/mount-tmp"
for directory in hooks skills plugins commands agents workflows rules output-styles projects; do
  mkdir -p "$root/config/.claude/$directory"
done
for file in settings.json CLAUDE.md statusline.sh; do : > "$root/config/.claude/$file"; done
echo '{}' > "$root/config/.claude.json"
cp "$SCRIPT_DIR/tests/runtime-probe.py" "$root/probe/bin/claude"
chmod 755 "$root/probe/bin/claude"
clean_env+=("CLAUDE_CONFIG_DIR=$root/config" "CONTEXT=$root/project"
  "CLAUDE_CONTAINER_DIR=$SCRIPT_DIR" "BUILD_CONTEXT_DIR=$root"
  "TEST_IMAGE=$image" "TEST_LOG_DIR=$results/details" "TEST_RUNTIME_USERNS=1")

if [[ "$build" == 1 ]]; then
  run_phase build 25m "${clean_env[@]}" bash "$SCRIPT_DIR/test-build.sh" --build-only
else
  phase=build
  outcome[build]=running
  if ! podman image exists "$image"; then echo "ERROR: 指定イメージがありません: $image" >&2; exit 1; fi
  outcome[build]='not run（--image で既存イメージを指定）'
fi
run_phase mounts 5m "${clean_env[@]}" "TMPDIR=$root/mount-tmp" "TEST_COMPOSE_PROJECT=$mount_project" \
  bash "$SCRIPT_DIR/test-build.sh" --config-ro-only

# UID の対応付け・image・検査用マウントを追加し、製品の ENTRYPOINT・CMD・cap_add は維持。
# Claude のバイナリ自体は --build-only で確認済み。ここでは対話・API 課金を発生させない。
python3 - "$image" "$root" <<'PYTHON'
import json
from pathlib import Path
import sys
image, root = sys.argv[1:]
config = {"services": {"claude-auth-workspace": {
    "image": image,
    "environment": {"PATH": "/runtime-probe/bin:/home/node/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
    "volumes": [f"{root}/probe:/runtime-probe:ro"],
}}}
Path(root, "compose.runtime.json").write_text(json.dumps(config))
PYTHON
compose=("${clean_env[@]}" podman compose -f "$SCRIPT_DIR/compose.yml" -f "$SCRIPT_DIR/tests/compose.runtime-userns.yml"
  -f "$root/compose.runtime.json" -p "$run_id" --in-pod false)
run_phase control-before 2m "${compose[@]}" run --rm -T --name "$run_id-control-before" \
  claude-auth-workspace python3 /runtime-probe/bin/claude --control-before
protected_rc=0
run_phase protected 5m "${compose[@]}" run --rm -T --name "$run_id-protected" claude-auth-workspace || protected_rc=$?
# entrypoint が検査プログラムを実行せず 0 で終わる回帰も成功にしない。
if [[ "$protected_rc" == 0 ]] && ! grep -qx 'RUNTIME_PROBE_OK' "$results/protected.log"; then
  echo 'ERROR: entrypoint から検査プログラムの完了まで到達していません' | tee -a "$results/protected.log" >&2
  protected_rc=1
  outcome[protected]='FAIL（検査プログラムの完了印なし）'
fi
# 保護検査の失敗時も対照を記録する。最初の失敗の終了コードは維持する。
control_rc=0
run_phase control-after 2m "${compose[@]}" run --rm -T --name "$run_id-control-after" \
  claude-auth-workspace python3 /runtime-probe/bin/claude --control-after || control_rc=$?
if [[ "$protected_rc" != 0 ]]; then exit "$protected_rc"; fi
exit "$control_rc"
