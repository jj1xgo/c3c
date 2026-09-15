#!/usr/bin/env python3
"""Claude の代わりに起動し、実 entrypoint 通過後の権限・IPv4 通信を検査する。"""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys


def connects(ip, port):
    try:
        with socket.create_connection((ip, port), timeout=5):
            return True
    except OSError as error:
        print(f"接続失敗 {ip}:{port}: {error}", flush=True)
        return False


def main():
    control = len(sys.argv) == 2 and sys.argv[1].startswith("--control-")
    targets_path = Path("/workspace/runtime-targets.json")
    if control and sys.argv[1] == "--control-before":
        try:
            targets = {
                host: socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
                for host in ("api.github.com", "example.com")
            }
        except socket.gaierror as error:
            print(f"not run: 対照コンテナで IPv4 の名前解決ができません: {error}")
            return 77
        targets_path.write_text(json.dumps(targets))
    else:
        targets = json.loads(targets_path.read_text())
    github_ip, blocked_ip = targets["api.github.com"], targets["example.com"]
    print(f"固定した接続先: GitHub={github_ip}, 非許可={blocked_ip}", flush=True)

    if control:
        # 否定検査が、相手の停止や runner の通信制約だけで成功しないための対照。
        for ip, port in ((github_ip, 443), (github_ip, 80), (blocked_ip, 443)):
            if not connects(ip, port):
                print("not run: 対照コンテナから接続できず、遮断の原因を判別できません")
                return 77
        print("[PASS] ファイアウォール適用前の対照から全接続先へ到達できます")
        return 0

    # setpriv を外す、capability を子へ継承する、root で起動する回帰を検出する。
    print(f"検査プロセスの UID:GID={os.getuid()}:{os.getgid()}", flush=True)
    if os.getuid() == 0:
        raise RuntimeError("検査プロセスが root で動いています")
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    for name in ("CapInh", "CapPrm", "CapEff", "CapAmb"):
        value = int(status[name].strip(), 16)
        print(f"{name}={value:x}", flush=True)
        if value:
            raise RuntimeError(f"{name} に capability が残っています")
    try:
        result = subprocess.run(["iptables", "-L", "OUTPUT", "-n"], capture_output=True, text=True, timeout=10)
    except FileNotFoundError as error:
        raise RuntimeError("iptables が見つからず、直接操作の拒否を検査できません") from error
    if result.returncode == 0:
        raise RuntimeError("非 root のプロセスから iptables を操作できています")
    print("[PASS] 非 root の子プロセスに capability がなく、iptables の直接操作も拒否されます")

    if not connects(github_ip, 443):
        raise RuntimeError("許可先の GitHub:443 に到達できません")
    print("[PASS] 許可 IP・許可ポートへの接続に成功しました")
    for ip, port in ((github_ip, 80), (blocked_ip, 443)):
        if connects(ip, port):
            raise RuntimeError(f"禁止した宛先・ポート {ip}:{port} に到達しました")
    print("[PASS] 許可 IP の非許可ポートと、非許可 IP への接続が拒否されます")
    print("RUNTIME_PROBE_OK", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        sys.exit(1)
