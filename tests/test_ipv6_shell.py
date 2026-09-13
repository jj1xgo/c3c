#!/usr/bin/env python3
"""IPv4 の自己検証が dual-stack の IPv6 成功に隠れないことを検査する。"""
import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class IPv4VerificationTests(unittest.TestCase):
    def run_probe(self, failure):
        source = (ROOT / 'init-firewall.sh').read_text()
        match = re.search(r'^verify_ipv4\(\) \{\n.*?^\}', source, re.M | re.S)
        self.assertIsNotNone(match, 'IPv4 に限定した自己検証関数がありません')
        harness = r'''set -euo pipefail
# DNS/ソケットだけを fixture にする。ホスト名接続なら IPv6 成功を模擬する。
dig() { printf '%s\n' 'github.example.net.' '192.0.2.42'; }
timeout() {
  [[ "${@: -1}" == 80 ]] && return 1
  [[ "${@: -2:1}" == 192.0.2.42 && "$FAILURE" == tcp ]] && return 1
  return 0
}
curl() {
  [[ "${@: -1}" == https://example.com ]] && return 7
  [[ " $* " == *' -4 '* && "$FAILURE" == https ]] && return 7
  return 0
}
'''
        return subprocess.run(['bash', '-c', harness + match[0] + '\nverify_ipv4'],
                              env={'PATH': '/usr/bin:/bin', 'FAILURE': failure},
                              text=True, capture_output=True, timeout=5)

    def test_ipv4_https_failure_stops_even_if_ipv6_would_succeed(self):
        response = self.run_probe('https')
        self.assertNotEqual(response.returncode, 0)
        self.assertIn('api.anthropic.com', response.stderr)

    def test_ipv4_tcp_failure_stops_even_if_hostname_would_succeed(self):
        response = self.run_probe('tcp')
        self.assertNotEqual(response.returncode, 0)
        self.assertIn('api.github.com:443', response.stderr)

    def test_ipv4_success_and_denied_port(self):
        self.assertEqual(self.run_probe('').returncode, 0)


if __name__ == '__main__':
    unittest.main()
