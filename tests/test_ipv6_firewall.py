#!/usr/bin/env python3
"""IPv6 の実処理を検査する。DNS とカーネルコマンドだけを固定する。"""
import importlib.util
import pathlib
import unittest
from unittest.mock import patch

PATH = pathlib.Path(__file__).resolve().parents[1] / 'ipv6-firewall.py'
fw = None
if PATH.exists():
    spec = importlib.util.spec_from_file_location('ipv6_firewall', PATH)
    fw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fw)


class IPv6Tests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(fw, 'IPv6 許可リストの実装がありません')
        self.calls = []
        self.rules = '-N CLAUDE_EGRESS6\n'
        self.answer = ';; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\n'
        self.fail_add = False
        self.patcher = patch.object(fw, 'command', self.command)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.firewall = fw.IPv6Firewall('443,22')

    def command(self, args):
        self.calls.append(args)
        if args[0] == 'dig':
            return self.answer
        if args[:2] == ['ip6tables', '-S']:
            return self.rules
        if self.fail_add and args[:2] == ['ip6tables', '-A']:
            raise fw.FirewallError('ルール追加失敗')
        return ''

    def mutations(self):
        return [c for c in self.calls if c[0] == 'ip6tables' and c[1] in ('-A', '-D')]

    def test_verify_fails_when_allowed_endpoint_is_unreachable(self):
        with patch.object(fw, 'command', side_effect=fw.FirewallError('IPv6 許可先に到達できません')):
            with self.assertRaisesRegex(fw.FirewallError, '許可先'):
                self.firewall.verify()

    def test_address_representation(self):
        self.assertEqual(fw.normalize_target('2001:0DB8:0000:0000:0000:0000:0000:0001'), '2001:db8::1')
        self.assertEqual(fw.normalize_target('fd00::1'), 'fd00::1')

    def test_special_addresses(self):
        for address in ['::', '::1', '::ffff:192.0.2.1', '::ffff:c000:201', 'ff02::1', 'fe80::1', '64:ff9b::c000:201']:
            with self.subTest(address=address):
                self.assertIsNone(fw.normalize_target(address))

    def test_invalid_address(self):
        for address in ['2001:::1', 'evil', '2001:db8::1%eth0', '2001:db8::1/64']:
            with self.subTest(address=address), self.assertRaises(fw.FirewallError):
                fw.normalize_target(address)

    def test_invalid_ports(self):
        for ports in ['443,0', '443,65536', '443,8000:7000', '443,80', '22', '443;true', '443:443']:
            with self.subTest(ports=ports), self.assertRaises(fw.FirewallError):
                fw.IPv6Firewall(ports)

    def test_all_domains_validate_before_dns(self):
        with self.assertRaises(fw.FirewallError):
            self.firewall.refresh(['valid.example', 'evil.example good.example'], 1000)
        self.assertEqual(self.calls, [])

    def test_dns_noerror_without_aaaa(self):
        self.firewall.refresh(['fixture.example'], 1000)
        self.assertEqual(self.mutations(), [])

    def test_dns_nxdomain(self):
        self.answer = ';; status: NXDOMAIN\n'
        self.firewall.refresh(['fixture.example'], 1000)
        self.assertEqual(self.mutations(), [])

    def test_dns_temporary_failure(self):
        self.answer = ';; status: SERVFAIL\n'
        with self.assertRaises(fw.FirewallError):
            self.firewall.refresh(['fixture.example'], 1000)

    def test_dns_bad_status_with_address(self):
        self.answer = ';; status: SERVFAIL\nfixture.example. 60 IN AAAA 2001:db8::1\n'
        with self.assertRaises(fw.FirewallError):
            self.firewall.refresh(['fixture.example'], 1000)
        self.assertEqual(self.mutations(), [])

    def test_dns_mixed_addresses(self):
        self.answer += 'fixture.example. 60 IN AAAA ::\nfixture.example. 60 IN AAAA 2001:0db8::1\n'
        self.firewall.refresh(['fixture.example'], 1000)
        added = [c for c in self.mutations() if c[1] == '-A']
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0][added[0].index('-d')+1], '2001:db8::1')
        self.assertEqual(added[0][added[0].index('--dports')+1], '443,22')

    def test_update_adds_before_deleting_matching_rules(self):
        self.rules += '\n'.join([
            '-A CLAUDE_EGRESS6 -d 2001:db8::1/128 -m comment --comment "domain=other.example;gen=900" -j ACCEPT',
            '-A CLAUDE_EGRESS6 -d 2001:db8::2/128 -m comment --comment "domain=fixture.example;gen=900" -j ACCEPT',
            '-A CLAUDE_EGRESS6 -d 2001:db8::1/128 -m comment --comment "domain=fixture.example;gen=900" -j ACCEPT',
            '-A CLAUDE_EGRESS6 -d 2001:0db8:0:0:0:0:0:1/128 -m comment --comment "domain=fixture.example;gen=899" -j ACCEPT',
        ])
        self.firewall.touch('2001:db8::1', 'fixture.example', 1000)
        mutations = self.mutations()
        self.assertEqual([c[1] for c in mutations], ['-A', '-D', '-D'])
        self.assertEqual([c[-1] for c in mutations[1:]], ['4', '3'])

    def test_add_failure_keeps_old_rules(self):
        self.rules += '-A CLAUDE_EGRESS6 -d 2001:db8::1/128 -m comment --comment "domain=fixture.example;gen=900" -j ACCEPT\n'
        self.fail_add = True
        with self.assertRaises(fw.FirewallError):
            self.firewall.touch('2001:db8::1', 'fixture.example', 1000)
        self.assertFalse(any(c[1] == '-D' for c in self.mutations()))

    def test_prune_expired_only_descending(self):
        self.rules += '\n'.join([
            '-A CLAUDE_EGRESS6 -d 2001:db8::1/128 -m comment --comment "domain=a.example;gen=819" -j ACCEPT',
            '-A CLAUDE_EGRESS6 -d 2001:db8:1::/48 -j ACCEPT',
            '-A CLAUDE_EGRESS6 -d 2001:db8::2/128 -m comment --comment "domain=b.example;gen=820" -j ACCEPT',
            '-A CLAUDE_EGRESS6 -d 2001:db8::3/128 -m comment --comment "domain=c.example;gen=1" -j ACCEPT',
        ])
        self.firewall.prune(820)
        self.assertEqual(self.mutations(), [['ip6tables','-D','CLAUDE_EGRESS6','4'], ['ip6tables','-D','CLAUDE_EGRESS6','1']])

    def test_tag_limit(self):
        domain = '.'.join(['a'*63]*3 + ['b'*41])
        self.firewall.touch('2001:db8::1', domain, 1700000000)
        added = self.mutations()[0]
        self.assertEqual(len(added[added.index('--comment')+1]), 255)
        self.calls.clear()
        with self.assertRaises(fw.FirewallError):
            self.firewall.touch('2001:db8::1', domain+'b', 1700000000)
        self.assertEqual(self.mutations(), [])

    def test_snapshot_error_not_hidden(self):
        with patch.object(fw, 'command', side_effect=fw.FirewallError('一覧取得失敗')):
            with self.assertRaises(fw.FirewallError):
                self.firewall.touch('2001:db8::1', 'fixture.example', 1000)

    def test_route_absent_stops_before_flush(self):
        with patch.object(fw, 'command', return_value='[]'):
            with self.assertRaisesRegex(fw.FirewallError, '既定経路'):
                self.firewall.prepare()

    def test_ip6tables_unavailable_stops_before_flush(self):
        def system(args):
            self.calls.append(args)
            if args[0] == 'ip':
                return '[{"gateway":"fe80::1","dev":"eth0"}]'
            raise fw.FirewallError('ip6tables 利用不可')
        with patch.object(fw, 'command', system), patch.object(pathlib.Path, 'read_text', return_value='0\n'):
            with self.assertRaisesRegex(fw.FirewallError, '利用不可'):
                self.firewall.prepare()
        self.assertFalse(any('-F' in c for c in self.calls))

    def test_verify_rejects_reachable_forbidden_destination(self):
        with self.assertRaisesRegex(fw.FirewallError, '禁止先へ到達'):
            self.firewall.verify()

    def test_github_prefix_does_not_allow_unspecified_space(self):
        with self.assertRaises(fw.FirewallError):
            self.firewall.add_network('::/0')
        self.assertEqual(self.mutations(), [])
        self.firewall.add_network('2606:50c0::/32')
        self.assertIn('2606:50c0::/32', self.mutations()[0])

    def test_prepare_required_icmp_dns_and_default_deny(self):
        def system(args):
            self.calls.append(args)
            if args[0] == 'ip': return '[{"gateway":"fe80::1","dev":"eth0"}]'
            return ''
        def files(path, *args, **kwargs):
            return 'nameserver 2001:db8::53\n' if str(path) == '/etc/resolv.conf' else '0\n'
        with patch.object(fw, 'command', system), patch.object(pathlib.Path, 'read_text', files):
            self.firewall.prepare()
        for chain in ['INPUT','OUTPUT','FORWARD']:
            self.assertIn(['ip6tables','-P',chain,'DROP'], self.calls)
        self.assertTrue(any('--icmpv6-type' in c and c[c.index('--icmpv6-type')+1]=='2' for c in self.calls))
        self.assertTrue(any('--icmpv6-type' in c and c[c.index('--icmpv6-type')+1]=='135' and '--hl-eq' in c for c in self.calls))
        dns = [c for c in self.calls if '--dport' in c and c[c.index('--dport')+1]=='53']
        self.assertEqual(len(dns), 2)
        self.assertTrue(all('2001:db8::53' in c for c in dns))
        self.assertTrue(any('REJECT' in c for c in self.calls))


if __name__ == '__main__':
    unittest.main()
