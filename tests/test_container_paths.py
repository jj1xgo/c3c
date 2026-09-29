#!/usr/bin/env python3
"""改名 第 2 段: コンテナ側のファイルが旧名のパス（/etc/claude-container・~/.config/claude-container）と
旧 env キー・旧 label を参照しないこと。v16 の compose はこれらにマウントしないので、参照が残ると承認記録・
秘密・許可リストを黙って読めなくなる。検出と案内のために旧名を扱う launcher（c3c）と lint.sh の否定検査は
この検査の対象外。コメントも検査する（コメントには旧名の識別子を綴らない）。"""
from pathlib import Path
import re
import unittest

REPO = Path(__file__).resolve().parents[1]
CONTAINER_SIDE = ('Dockerfile.claude', 'compose.yml', 'compose.ipv6.yml', 'compose.codex-preflight.yml',
                  'compose.plugins-alias.yml', 'compose.shared-home.yml', 'compose.shared-host.yml',
                  'compose.agents.yml', 'compose.codex-plugins.yml', 'entrypoint.sh', 'init-firewall.sh',
                  'ipv6-firewall.py', 'firewall-refresh.py', 'git-askpass.sh', 'codex-launcher.sh',
                  'codex-mcp-audit.py', 'claude-project-audit.py')
LEGACY = re.compile(r'/etc/claude-container|\.config/claude-container')


class ContainerPathTests(unittest.TestCase):
    def test_container_side_files_do_not_reference_legacy_names(self):
        for name in CONTAINER_SIDE:
            with self.subTest(file=name):
                text = (REPO / name).read_text()
                hits = [f'{i}: {line.strip()}' for i, line in enumerate(text.splitlines(), 1) if LEGACY.search(line)]
                self.assertEqual(hits, [])


if __name__ == '__main__':
    unittest.main()
