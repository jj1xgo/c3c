#!/usr/bin/python3
"""IPv6 の許可ルールを管理する。root 所有の境界アセットとして配置する。"""
import argparse
import ipaddress
import json
import pathlib
import re
import shlex
import subprocess
import sys

CHAIN = 'CLAUDE_EGRESS6'
# init-firewall.sh の GRACE_WINDOW_SECONDS（15秒×12回）と同期させる。
GRACE_SECONDS = 180
TARGET_RANGES = (ipaddress.IPv6Network('2000::/3'), ipaddress.IPv6Network('fc00::/7'))
DOMAIN = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?')
TAG = re.compile(r'domain=([A-Za-z0-9.-]+);gen=([0-9]+)')


class FirewallError(Exception):
    """起動を中止、または更新サイクルを失敗として報告するエラー。"""


def command(args):
    """シェルを介さず、外部処理の失敗とタイムアウトを呼び出し元へ渡す。"""
    try:
        result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FirewallError(f'{args[0]} を実行できません: {exc}') from exc
    if result.returncode:
        raise FirewallError(f'{args[0]} が失敗しました（終了コード{result.returncode}）: {result.stderr.strip()}')
    return result.stdout


def normalize_target(value):
    """許可対象の unicast を正規化する。特殊用途は None、不正書式はエラー。"""
    try:
        if '%' in value or '/' in value:
            raise ValueError('ゾーン・プレフィックス付きの応答')
        address = ipaddress.IPv6Address(value)
    except ValueError as exc:
        raise FirewallError(f'不正な IPv6 アドレスです: {value!r}') from exc
    if not any(address in network for network in TARGET_RANGES):
        return None
    return str(address)


def validate_domains(domains):
    # 呼び出し元も検査するが、専用アセットの入口でも全件を先に確認する。
    for domain in domains:
        name = domain.removesuffix('.')
        if len(name) > 253 or not all(DOMAIN.fullmatch(label) for label in name.split('.')):
            raise FirewallError(f'不正な IPv6 許可ホスト名です: {domain!r}')


class IPv6Firewall:
    def __init__(self, ports):
        self.ports = ports
        slots = 0
        has_https = False
        for item in ports.split(','):
            if not re.fullmatch(r'[0-9]{1,5}(?::[0-9]{1,5})?', item):
                raise FirewallError('IPv6 許可ポートの書式が不正です')
            parts = [int(number) for number in item.split(':')]
            lo, hi = parts[0], parts[-1]
            slots += len(parts)
            if not 1 <= lo <= hi <= 65535 or (len(parts) == 2 and lo == hi) or lo <= 80 <= hi:
                raise FirewallError('IPv6 許可ポートの範囲が不正です')
            has_https = has_https or lo <= 443 <= hi
        if slots > 15 or not has_https:
            raise FirewallError('IPv6 許可ポートは443を含め、multiportの15枠以内にしてください')
        # 呼び出し元に依存せず十進表記を ip6tables へ渡す。
        self.ports = ','.join(':'.join(str(int(n)) for n in item.split(':')) for item in ports.split(','))

    def table(self, *args):
        return command(['ip6tables', *args])

    def prepare(self):
        routes = json.loads(command(['ip', '-j', '-6', 'route', 'show', 'default']))
        if not routes:
            raise FirewallError('IPv6 の既定経路がありません。Podman/pasta の設定を確認してください')
        for name in ('all', 'default'):
            value = pathlib.Path(f'/proc/sys/net/ipv6/conf/{name}/disable_ipv6').read_text().strip()
            if value != '0':
                raise FirewallError(f'IPv6 が無効です: {name}。IPv6 用 Compose 構成を確認してください')
        self.table('-L')
        self.table('-F')
        self.table('-X')
        for chain in ('INPUT', 'OUTPUT', 'FORWARD'):
            self.table('-P', chain, 'DROP')
        self.table('-N', CHAIN)
        self.table('-A', 'INPUT', '-i', 'lo', '-j', 'ACCEPT')
        self.table('-A', 'OUTPUT', '-o', 'lo', '-j', 'ACCEPT')
        for chain in ('INPUT', 'OUTPUT'):
            self.table('-A', chain, '-m', 'state', '--state', 'ESTABLISHED,RELATED', '-j', 'ACCEPT')
            # ICMPv6 エラーと近隣探索。TCP/UDP 全許可の代わりには使わない。
            for kind in ('1', '2', '3', '4'):
                self.table('-A', chain, '-p', 'ipv6-icmp', '--icmpv6-type', kind, '-j', 'ACCEPT')
            for kind in ('135', '136'):
                self.table('-A', chain, '-p', 'ipv6-icmp', '--icmpv6-type', kind, '-m', 'hl', '--hl-eq', '255', '-j', 'ACCEPT')
        self.table('-A', 'OUTPUT', '-d', 'ff02::2', '-p', 'ipv6-icmp', '--icmpv6-type', '133', '-m', 'hl', '--hl-eq', '255', '-j', 'ACCEPT')
        self.table('-A', 'INPUT', '-s', 'fe80::/10', '-p', 'ipv6-icmp', '--icmpv6-type', '134', '-m', 'hl', '--hl-eq', '255', '-j', 'ACCEPT')
        for line in pathlib.Path('/etc/resolv.conf').read_text().splitlines():
            fields = line.split()
            if len(fields) < 2 or fields[0] != 'nameserver' or ':' not in fields[1]:
                continue
            raw, _, zone = fields[1].partition('%')
            address = str(ipaddress.IPv6Address(raw))
            interface = []
            if zone:
                if not re.fullmatch(r'[A-Za-z0-9_.-]+', zone) or not pathlib.Path('/sys/class/net', zone).exists():
                    raise FirewallError('IPv6 DNS リゾルバの interface が不正です')
                interface = ['-o', zone]
            for protocol in ('udp', 'tcp'):
                self.table('-A', 'OUTPUT', '-d', address, *interface, '-p', protocol, '--dport', '53', '-j', 'ACCEPT')
        self.table('-A', 'OUTPUT', '-j', CHAIN)
        self.table('-A', 'OUTPUT', '-j', 'REJECT', '--reject-with', 'icmp6-adm-prohibited')

    def add_network(self, value):
        network = ipaddress.IPv6Network(value, strict=False)
        if not any(network.subnet_of(allowed) for allowed in TARGET_RANGES):
            raise FirewallError(f'IPv6 許可範囲外の CIDR です: {value}')
        self.table('-A', CHAIN, '-d', str(network), '-p', 'tcp', '-m', 'multiport', '--dports', self.ports, '-j', 'ACCEPT')

    def rules(self):
        # 行番号はタグなしも含む全 -A 行で数える。取得失敗を空一覧にしない。
        result = []
        index = 0
        for line in self.table('-S', CHAIN).splitlines():
            fields = shlex.split(line)
            if fields[:2] != ['-A', CHAIN]:
                continue
            index += 1
            if '--comment' not in fields or '-d' not in fields:
                continue
            tag = TAG.fullmatch(fields[fields.index('--comment') + 1])
            if not tag:
                continue
            network = ipaddress.IPv6Network(fields[fields.index('-d') + 1], strict=False)
            if network.prefixlen != 128:
                continue
            result.append((index, str(network.network_address), tag[1], int(tag[2])))
        return result

    def touch(self, address, domain, generation):
        validate_domains([domain])
        address = normalize_target(address)
        if address is None:
            raise FirewallError('IPv6 の特殊用途アドレスはルールに追加できません')
        comment = f'domain={domain};gen={generation}'
        if len(comment.encode('ascii')) > 255:
            raise FirewallError(f'IPv6 世代タグが255バイトを超えます: {domain}')
        previous = [idx for idx, ip, name, _ in self.rules() if ip == address and name == domain]
        self.table('-A', CHAIN, '-d', address, '-p', 'tcp', '-m', 'multiport', '--dports', self.ports,
                   '-m', 'comment', '--comment', comment, '-j', 'ACCEPT')
        for index in reversed(previous):
            self.table('-D', CHAIN, str(index))

    def prune(self, cutoff):
        for index, _, _, generation in reversed(self.rules()):
            if generation < cutoff:
                self.table('-D', CHAIN, str(index))

    def refresh(self, domains, generation):
        validate_domains(domains)
        errors = []
        for domain in domains:
            try:
                output = command(['dig', '+noall', '+answer', '+comments', '+time=2', '+tries=2', 'AAAA', domain])
                status = re.search(r'status:\s*([A-Z]+)', output)
                if not status or status[1] not in ('NOERROR', 'NXDOMAIN'):
                    raise FirewallError(f'{domain} の AAAA を解決できませんでした')
                if status[1] == 'NXDOMAIN':
                    print(f'WARNING: {domain} の AAAA は NXDOMAIN のためスキップします', file=sys.stderr)
                    continue
                seen = set()
                for line in output.splitlines():
                    fields = line.split()
                    if len(fields) < 5 or fields[3] != 'AAAA':
                        continue
                    address = normalize_target(fields[4])
                    if address is None:
                        print(f'WARNING: {domain} -> {fields[4]} は IPv6 許可範囲外のためスキップします', file=sys.stderr)
                    elif address not in seen:
                        self.touch(address, domain, generation)
                        seen.add(address)
            except FirewallError as exc:
                errors.append(str(exc))
        # 一時的な解決失敗でも古い許可を永続化しない。
        self.prune(generation - GRACE_SECONDS)
        if errors:
            raise FirewallError(' / '.join(errors))

    def verify(self):
        common = ['curl', '-6', '--noproxy', '*', '--connect-timeout', '5', '--max-time', '15', '-sS', '-o', '/dev/null']
        command([*common, 'https://api.anthropic.com'])
        for url in ('https://example.com', 'http://api.anthropic.com'):
            try:
                command([*common, url])
            except FirewallError:
                continue
            raise FirewallError(f'IPv6 の禁止先へ到達できました: {url}')
        print('IPv6 検証 OK: Anthropic HTTPS 許可、未許可ドメインと80番を遮断')


def main():
    parser = argparse.ArgumentParser(description='IPv6 許可リストの初期化・更新・検証')
    parser.add_argument('mode', choices=('prepare', 'refresh', 'verify'))
    parser.add_argument('--ports', required=True)
    parser.add_argument('--generation', type=int)
    args = parser.parse_args()
    try:
        firewall = IPv6Firewall(args.ports)
        if args.mode == 'prepare':
            meta = json.loads(pathlib.Path('/etc/claude-container/github-meta.json').read_text())
            networks = sorted({value for key in ('web', 'api', 'git') for value in meta[key] if ':' in value})
            firewall.prepare()
            for network in networks:
                firewall.add_network(network)
        elif args.mode == 'refresh':
            if args.generation is None or args.generation < 0:
                raise FirewallError('IPv6 更新には非負の世代時刻が必要です')
            firewall.refresh([line for line in sys.stdin.read().splitlines() if line], args.generation)
        else:
            firewall.verify()
    except (FirewallError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f'ERROR: IPv6 ファイアウォール: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
