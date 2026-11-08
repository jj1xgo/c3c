#!/bin/bash
# GitHub Copilot CLI の起動口。Dockerfile.claude が、opt-in（copilot-version.txt に版がある）のときだけ、
# このファイルで npm の symlink /usr/local/bin/copilot を置き換える。名前で呼ばれる copilot（Claude 経路の
# Bash ツール、ログインシェル、podman exec）はすべてここを通る。
#
# Copilot の command sandboxing（MXC の bubblewrap、通信なし）を c3c のコンテナの中で動かすため、次をこの順で
# 行い、どれかを満たせなければ ERROR を出して rc 1 で止まる（Copilot を起動しない。fail-closed）。
#   1. bwrap の中継（copilot-bwrap-shim.sh）と Copilot の実体があること
#   2. 作業ディレクトリが、認証や秘密の置き場（/home/node 自身とその祖先、/home/node の直下の . で始まる
#      エントリとその下）でないこと。sandbox はその作業ディレクトリを読み取りだけで見せる
#   3. COPILOT_HOME の settings.json を、root が持つ雛形から毎回作り直し、作業ディレクトリを readonlyPaths に
#      入れて、sandbox の設定を検査する（弱めた設定、未知のキー、真偽値でない値は不合格）
#   4. トークンを SECRETS_DIR の COPILOT_PAT から bash の組み込みで読む（印字できる ASCII の 1 行だけ）
#   5. 環境を allowlist に絞り、中継を PATH の先頭にして npm-loader.js を exec する
# トークンは外部コマンドの引数にしない（env -i を使わない。並行する sandbox からもコマンドラインは見える）。
# 固定パスは環境変数で差し替えられない（readonly、上書き口を作らない）。設定の検査は python3 -I で行い、
# パスは引数で渡す。
set -u
# 呼び出し元の xtrace（bash -x、環境の SHELLOPTS）でトークンが stderr に出ないよう、最初に止める。
set +x +v
# 起動口が使う名前を、呼び出し元が export した同じ名前から切り離す（export のまま値を入れると、下の環境の
# 絞り込みで消える）。
unset -v cwd rel token name saved_lc_all saved_lc_all_set

readonly CONTAINER_HOME=/home/node
readonly COPILOT_BWRAP_DIR=/usr/local/libexec/c3c/copilot-bwrap
readonly COPILOT_JS=/usr/local/lib/node_modules/@github/copilot/npm-loader.js
readonly COPILOT_HOME=/home/node/.copilot
readonly SETTINGS_TEMPLATE=/etc/c3c/copilot-settings.json
readonly TOKEN_FILE=/home/node/.config/c3c/secrets/COPILOT_PAT
readonly PYTHON3=/usr/bin/python3
readonly FLOCK=/usr/bin/flock
# 雛形の deniedPaths の必須の 2 つ。作業ディレクトリ（readonlyPaths に入る）をこれらと重ねない。
readonly SANDBOX_TMP=/tmp
readonly SECRETS_DIR=/home/node/.config/c3c/secrets
readonly SAFE_PATH="$COPILOT_BWRAP_DIR:/usr/local/bin:/usr/bin:/bin"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

# 1. 中継と実体
if [ ! -f "$COPILOT_BWRAP_DIR/bwrap" ] || [ ! -x "$COPILOT_BWRAP_DIR/bwrap" ]; then
  fail "Copilot の sandbox 用の bwrap の中継（$COPILOT_BWRAP_DIR/bwrap）がありません。-b で再ビルドしてください。"
fi
if [ ! -f "$COPILOT_JS" ] || [ ! -x "$COPILOT_JS" ]; then
  fail "Copilot CLI（$COPILOT_JS）がありません。-b で再ビルドしてください。"
fi

# 2. 作業ディレクトリ。比較は / で区切った要素の単位で行う（文字列の前方一致にしない）。
# $(...) は末尾の改行を落とすので、番兵の文字を付けて受け取る。改行・制御文字を含むパスは断る。
if ! cwd="$(pwd -P 2>/dev/null && printf x)" || [ "${cwd%x}" = "$cwd" ]; then
  fail "作業ディレクトリを解決できません（消えたディレクトリの中などで起動していないか確かめてください）。"
fi
cwd="${cwd%x}"
cwd="${cwd%$'\n'}"
if [ -z "$cwd" ] || [ "${cwd#/}" = "$cwd" ] || [[ "$cwd" == *[[:cntrl:]]* ]]; then
  fail "作業ディレクトリを解決できません（改行や制御文字を含むパスでは起動しません）。"
fi
refuse_cwd() {
  fail "作業ディレクトリ $cwd では起動しません（$1）。Copilot に見せてよいディレクトリ（/workspace や $CONTAINER_HOME/copilot-work など）で起動してください。"
}
if [ "$cwd" = / ] || [ "$cwd" = "$CONTAINER_HOME" ]; then
  refuse_cwd "$CONTAINER_HOME とその祖先は、認証や秘密の置き場を含むため"
fi
case "$CONTAINER_HOME" in
  "$cwd"/*) refuse_cwd "$CONTAINER_HOME とその祖先は、認証や秘密の置き場を含むため" ;;
esac
for denied in "$SANDBOX_TMP" "$SECRETS_DIR"; do
  case "$cwd" in
    "$denied" | "$denied"/*) refuse_cwd "$denied とその下は sandbox で隠す場所のため" ;;
  esac
done
case "$cwd" in
  "$CONTAINER_HOME"/*)
    rel="${cwd#"$CONTAINER_HOME"/}"
    case "${rel%%/*}" in
      .*) refuse_cwd "$CONTAINER_HOME の直下の . で始まるエントリは、認証や設定の置き場のため" ;;
    esac
    ;;
esac

# 3. settings.json は全起動で 1 つを共有するので、別の copilot が動いている間は起動しない（作り直した設定を
#    取り合わないため）。lock は fd 9（読み取りだけ）を exec した Copilot が持ち続け、終わると外れる。
if [ -L "$COPILOT_HOME" ] || { [ -e "$COPILOT_HOME" ] && [ ! -d "$COPILOT_HOME" ]; }; then
  fail "$COPILOT_HOME がディレクトリではありません（symlink を含む）。"
fi
if [ ! -d "$COPILOT_HOME" ] && ! mkdir -m 700 "$COPILOT_HOME" 2>/dev/null; then
  fail "$COPILOT_HOME を作れません。"
fi
readonly LOCK_FILE="$COPILOT_HOME/.c3c-launch.lock"
if [ -L "$LOCK_FILE" ] || { [ -e "$LOCK_FILE" ] && [ ! -f "$LOCK_FILE" ]; }; then
  fail "$LOCK_FILE が通常のファイルではありません（symlink を含む）。"
fi
if ! { : >> "$LOCK_FILE" && exec 9< "$LOCK_FILE"; } 2>/dev/null; then
  fail "$LOCK_FILE を開けません。"
fi
if ! "$FLOCK" -n 9; then
  fail "別の copilot が動いています（$COPILOT_HOME の settings.json を共有するため、並行して起動しません）。"
fi

#    sandbox の設定を雛形から作り直して検査する。
if ! "$PYTHON3" -I -c '
import json, os, sys

template_path, home, settings_path, cwd, required_tmp, required_secrets = sys.argv[1:7]
REQUIRED_DENIED = [required_tmp, required_secrets]


def die(message):
    print("ERROR: " + message, file=sys.stderr)
    sys.exit(1)


def check(doc, readonly_paths):
    """sandbox の設定が目標の値か。readonly_paths が None なら雛形（readonlyPaths を持たない）として見る。"""
    if not isinstance(doc, dict) or not isinstance(doc.get("sandbox"), dict):
        return "sandbox の設定がありません"
    sandbox = doc["sandbox"]
    allowed = {"enabled", "allowBypass", "addCurrentWorkingDirectory", "allowDevToolAccess", "auth",
               "sandboxMcpServers", "sandboxLspServers", "userPolicy"}
    if set(sandbox) - allowed:
        return "sandbox に未知のキーがあります: " + ", ".join(sorted(set(sandbox) - allowed))
    for key in ("enabled", "sandboxMcpServers", "sandboxLspServers"):
        if sandbox.get(key) is not True:
            return "sandbox." + key + " が true ではありません"
    for key in ("allowBypass", "allowDevToolAccess", "addCurrentWorkingDirectory"):
        if sandbox.get(key) is not False:
            return "sandbox." + key + " が false ではありません"
    auth = sandbox.get("auth")
    if not isinstance(auth, dict) or set(auth) != {"git", "gh"} or auth["git"] is not False or auth["gh"] is not False:
        return "sandbox.auth が {git: false, gh: false} ではありません"
    policy = sandbox.get("userPolicy")
    if not isinstance(policy, dict) or set(policy) - {"network", "filesystem"}:
        return "sandbox.userPolicy に未知のキーがあるか、形が違います"
    network = policy.get("network")
    if (not isinstance(network, dict) or set(network) != {"allowOutbound", "allowLocalNetwork"}
            or network["allowOutbound"] is not False or network["allowLocalNetwork"] is not False):
        return "sandbox.userPolicy.network が {allowOutbound: false, allowLocalNetwork: false} ではありません"
    filesystem = policy.get("filesystem")
    expected_keys = {"deniedPaths"} if readonly_paths is None else {"deniedPaths", "readonlyPaths"}
    if not isinstance(filesystem, dict) or set(filesystem) != expected_keys:
        return "sandbox.userPolicy.filesystem のキーが " + ", ".join(sorted(expected_keys)) + " ではありません"
    denied = filesystem["deniedPaths"]
    if not isinstance(denied, list) or not all(isinstance(p, str) for p in denied):
        return "deniedPaths が文字列の配列ではありません"
    missing = [p for p in REQUIRED_DENIED if p not in denied]
    if missing:
        return "deniedPaths に " + ", ".join(missing) + " がありません"
    if readonly_paths is not None and filesystem["readonlyPaths"] != readonly_paths:
        return "readonlyPaths が作業ディレクトリだけではありません"
    return None


try:
    with open(template_path, encoding="utf-8") as f:
        template = json.load(f)
except (OSError, ValueError) as e:
    die("sandbox の設定の雛形 " + template_path + " を読めません（" + type(e).__name__ + "）。-b で再ビルドしてください。")
problem = check(template, None)
if problem:
    die("sandbox の設定の雛形 " + template_path + " が不正です: " + problem + "。-b で再ビルドしてください。")

if os.path.islink(home) or (os.path.lexists(home) and not os.path.isdir(home)):
    die(home + " がディレクトリではありません（symlink を含む）。")
if not os.path.lexists(home):
    os.mkdir(home, 0o700)
os.chmod(home, 0o700)
if os.path.islink(settings_path) or (os.path.lexists(settings_path) and not os.path.isfile(settings_path)):
    die(settings_path + " が通常のファイルではありません（symlink を含む）。")

settings = template
settings["sandbox"]["userPolicy"]["filesystem"]["readonlyPaths"] = [cwd]
tmp = settings_path + ".tmp." + str(os.getpid())
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(settings, f)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, settings_path)
except BaseException:
    if os.path.lexists(tmp):
        os.unlink(tmp)
    raise

with open(settings_path, encoding="utf-8") as f:
    written = json.load(f)
problem = check(written, [cwd])
if problem:
    die(settings_path + " の sandbox の設定が不正です: " + problem + "。")
' "$SETTINGS_TEMPLATE" "$COPILOT_HOME" "$COPILOT_HOME/settings.json" "$cwd" "$SANDBOX_TMP" "$SECRETS_DIR"; then
  fail "sandbox の設定を用意できないため、Copilot を起動しません。"
fi

# 4. トークン。ファイル全体を bash の組み込みで読む（NUL があれば read は 0 を返すので止める）。
if [ ! -f "$TOKEN_FILE" ] || [ ! -r "$TOKEN_FILE" ]; then
  fail "Copilot のトークン $TOKEN_FILE（COPILOT_PAT）がありません。SECRETS_DIR の直下に、Copilot Requests の権限だけの PAT を COPILOT_PAT として置いてください。"
fi
token=""
if IFS= read -r -d '' token < "$TOKEN_FILE"; then
  token=""
  fail "$TOKEN_FILE（COPILOT_PAT）に NUL が含まれています。"
fi
token="${token%$'\n'}"
saved_lc_all="${LC_ALL-}"
saved_lc_all_set="${LC_ALL+set}"
LC_ALL=C
if [[ ! "$token" =~ ^[!-~]+$ ]]; then
  token=""
  fail "$TOKEN_FILE（COPILOT_PAT）は、印字できる ASCII の 1 行（空白・改行・制御文字を含まない）にしてください。"
fi
if [ -n "$saved_lc_all_set" ]; then
  LC_ALL="$saved_lc_all"
else
  unset LC_ALL
fi

# 5. 環境を allowlist に絞る（bash の組み込みだけで行う）。
for name in $(compgen -e); do
  case "$name" in
    HOME | LANG | LC_ALL | LC_CTYPE | TERM | TZ | NO_COLOR | COLORTERM) ;;
    *)
      # 起動口の readonly の定数と同じ名前（呼び出し元が export した COPILOT_HOME など）は unset できない。
      # 値は readonly の代入で固定値に替わっているので、export の印だけを外す。
      # shellcheck disable=SC2163  # 名前を値として渡し、その名前の export の印を外す（意図どおり）
      unset "$name" 2>/dev/null || export -n "$name" 2>/dev/null \
        || { token=""; fail "環境変数 $name を消せないため、Copilot を起動しません。"; }
      ;;
  esac
done
# export された関数（環境の BASH_FUNC_*）も Copilot へ渡さない。起動口自身の関数（fail など）も消えるので、
# ここより後で fail を呼ばない。
for name in $(compgen -A function); do
  unset -f "$name"
done
export PATH="$SAFE_PATH"
export COPILOT_HOME
export COPILOT_AUTO_UPDATE=false
export COPILOT_GITHUB_TOKEN="$token"
unset token saved_lc_all saved_lc_all_set name denied cwd rel
exec "$COPILOT_JS" "$@"
