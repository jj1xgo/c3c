#!/bin/bash
# Deny-by-default egress allowlist. Ported from the official Anthropic devcontainer
# (anthropics/claude-code .devcontainer/init-firewall.sh) with these deviations:
#   - No ipset: rootless podman cannot autoload the host's ip_set kernel module,
#     so plain per-CIDR iptables rules in a dedicated chain are used instead.
#   - DNS egress is limited to the resolvers in /etc/resolv.conf, not port 53 at large.
#   - IPv6 egress is dropped entirely: the allowlist resolves A records only, and
#     upstream's IPv4-only rules would otherwise leave IPv6 (pasta) as a bypass.
#   - Extra allowed domains come from /etc/claude-container/allowed-domains.txt,
#     baked into the image at build time (root-owned, not writable by node).
#   - Domain-backed CIDR rules carry a generation tag (see add_cidr_tagged below)
#     so `--refresh-domains` mode can keep up with short-TTL CDN IP rotation
#     without a full rule flush (observed 2026-07: cyberjapandata.gsi.go.jp
#     behind CloudFront rotates its entire A-record set every 13-60s, and a
#     one-shot startup resolution goes stale well within a long session).
# Runs as root via sudo from entrypoint.sh. Must stay fail-closed on the initial
# run: any error aborts container startup (opt out with CLAUDE_CONTAINER_NO_FIREWALL=1).
# `--refresh-domains` mode (see bottom) is a lightweight, fail-open exception to
# that rule — it's a periodic background touch-up, not the startup safety gate.
set -euo pipefail
IFS=$'\n\t'

ALLOWED_DOMAINS_FILE=/etc/claude-container/allowed-domains.txt
ALLOWED_PORTS_FILE=/etc/claude-container/allowed-ports.txt
CHAIN=CLAUDE_EGRESS
# Shortest observed CDN TTL was 13s; refresh slightly slower than that so a
# missed tick is caught by the next one rather than by chasing every wobble.
# The sleep itself lives in entrypoint.sh's refresh loop — keep the two in sync;
# here the constant sizes the grace window below.
REFRESH_INTERVAL_SECONDS=15
# 12 refresh cycles' worth of grace: absorbs a CDN answering with only a
# subset of its live edge IPs on any single query, and transient resolver
# hiccups, before a domain's now-unused IP is finally pruned.
GRACE_WINDOW_SECONDS=$((REFRESH_INTERVAL_SECONDS * 12))

MODE=init
if [ -n "${1:-}" ]; then
  if [ "$1" = "--refresh-domains" ]; then
    MODE=refresh
  else
    echo "ERROR: unknown argument: $1 (expected --refresh-domains or no argument)" >&2
    exit 1
  fi
fi

# Ports that CHAIN-routed ACCEPT rules (add_cidr/add_cidr_tagged below) permit
# on an otherwise-allowed IP (claude-container#31). Read once here so both
# `init` and `--refresh-domains` modes see the same value. Does NOT apply to
# the DNS resolver rules or the host-network rule in full_init() — those bypass
# CHAIN entirely and stay unrestricted (see the comment where CHAIN is created).
resolve_allowed_ports() {
  local -a ports=()
  local raw
  if [ -f "$ALLOWED_PORTS_FILE" ]; then
    # `|| [ -n "$raw" ]` keeps a final line that has no trailing newline
    # (read returns non-zero on it but still fills the variable; without
    # this the last entry was silently dropped — claude-container#49).
    while IFS= read -r raw || [ -n "$raw" ]; do
      raw="${raw%%#*}"
      raw="$(printf '%s' "$raw" | tr -d '[:space:]')"
      [ -n "$raw" ] || continue
      if [[ ! "$raw" =~ ^[0-9]{1,5}(:[0-9]{1,5})?$ ]]; then
        echo "ERROR: invalid entry in $ALLOWED_PORTS_FILE: '$raw' (expected a port or port:port range, e.g. 443 or 8000:8010)" >&2
        exit 1
      fi
      ports+=("$raw")
    done < "$ALLOWED_PORTS_FILE"
  fi
  if [ "${#ports[@]}" -eq 0 ]; then
    ports=(443 22)
  fi
  if [ "${#ports[@]}" -gt 15 ]; then
    echo "ERROR: $ALLOWED_PORTS_FILE lists ${#ports[@]} ports/ranges; iptables' multiport match supports at most 15" >&2
    exit 1
  fi
  # The startup self-check in full_init() assumes 443 is reachable and 80 is
  # blocked on api.github.com. A list that violates either assumption used to
  # fail there with a message that read like a network problem ("unable to
  # reach ...:443") or a broken rule ("port restriction not enforced"), so
  # validate the list here with the real reason (claude-container#49).
  # Ranges are inclusive; 10# forces decimal so leading zeros (e.g. 080) are
  # not read as octal.
  local entry lo hi has_443=0 has_80=0
  for entry in "${ports[@]}"; do
    lo="${entry%%:*}"; hi="${entry##*:}"
    if (( 10#$lo <= 443 && 443 <= 10#$hi )); then has_443=1; fi
    if (( 10#$lo <= 80 && 80 <= 10#$hi )); then has_80=1; fi
  done
  if [ "$has_443" -eq 0 ]; then
    echo "ERROR: $ALLOWED_PORTS_FILE must include 443 (api.anthropic.com, api.github.com and the startup self-check need it)" >&2
    exit 1
  fi
  if [ "$has_80" -eq 1 ]; then
    echo "ERROR: $ALLOWED_PORTS_FILE must not allow port 80 (the startup self-check uses api.github.com:80 as the blocked-port probe)" >&2
    exit 1
  fi
  local IFS=,
  ALLOWED_PORTS="${ports[*]}"
}
resolve_allowed_ports

# Plain per-CIDR ACCEPT, no generation tag. Used for ranges that don't rotate
# on a short TTL (GitHub's build-time snapshot) and so never need pruning.
add_cidr() {
  local cidr="$1" origin="$2"
  if [[ ! "$cidr" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(/[0-9]{1,2})?$ ]]; then
    echo "Skipping non-IPv4 range from $origin: $cidr"
    return 0
  fi
  iptables -A "$CHAIN" -d "$cidr" -p tcp -m multiport --dports "$ALLOWED_PORTS" -j ACCEPT
}

# Same as add_cidr, but tags the rule with domain+generation so
# prune_stale_domain_rules() can find and expire it later. Used only for the
# per-domain dynamic resolution loop below, never for GitHub CIDRs or the
# host-network rule (neither of those rotates on a short TTL).
add_cidr_tagged() {
  local cidr="$1" domain="$2" generation="$3"
  if [[ ! "$cidr" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(/[0-9]{1,2})?$ ]]; then
    echo "Skipping non-IPv4 range from $domain: $cidr"
    return 0
  fi
  if [[ ! "$domain" =~ ^[A-Za-z0-9.-]+$ ]]; then
    echo "ERROR: refusing to tag rule with unsafe domain string: $domain" >&2
    return 1
  fi
  iptables -A "$CHAIN" -d "$cidr" -p tcp -m multiport --dports "$ALLOWED_PORTS" -m comment --comment "domain=${domain};gen=${generation}" -j ACCEPT
}

# Adds a fresh tagged rule for (domain, ip); if a rule for that exact pair
# already exists, drops the old one so only the generation tag effectively
# "moves forward" instead of accumulating a duplicate on every refresh tick.
# New rule is added *before* the old one is deleted, so the IP stays allowed
# throughout — no flush, no gap.
# NOTE: assumes `iptables -S` renders a bare host as "-d IP/32" and that,
# after stripping the leading "-N CHAIN" line, grep's 1-indexed match line
# number equals the rule's position for `iptables -D CHAIN <N>`. Confirmed
# empirically (iptables 1.8.11/nf_tables) that -S always emits core fields
# (-A CHAIN -d IP/32 -p ...) before match-extension flags (-m multiport,
# -m comment) regardless of the order they were passed on the add_cidr* call,
# so the "-d ${ip}/32 " grep below keeps matching after the port restriction
# (claude-container#31) was added to add_cidr_tagged.
add_or_touch_domain_ip() {
  local ip="$1" domain="$2" generation="$3"
  local existing_idx
  existing_idx=$(iptables -S "$CHAIN" | tail -n +2 | \
    grep -nF -- "-d ${ip}/32 " | grep -F "domain=${domain};" | \
    cut -d: -f1 | head -n1 || true)
  add_cidr_tagged "$ip" "$domain" "$generation" || return 1
  if [ -n "$existing_idx" ]; then
    iptables -D "$CHAIN" "$existing_idx"
  fi
}

# Claude Code endpoints + project-specific domains, one per line.
build_domain_list() {
  local -a base_domains=(
    api.anthropic.com
    claude.ai
    console.anthropic.com
    statsig.anthropic.com
    statsig.com
    sentry.io
  )
  printf '%s\n' "${base_domains[@]}"
  if [ -f "$ALLOWED_DOMAINS_FILE" ]; then
    grep -Ev '^\s*(#|$)' "$ALLOWED_DOMAINS_FILE" | tr -d ' \t'
  fi
}

# Resolves every allowed domain and applies add_or_touch_domain_ip for each
# returned IP. A single domain failing to resolve does not abort the others
# (fail-open at this layer) — callers decide what a nonzero return means:
# full_init treats it as fatal (fail-closed startup gate), do_refresh logs
# and retries next cycle (fail-open background touch-up).
#
# NXDOMAIN (the domain no longer exists at all, e.g. statsig.anthropic.com as
# of 2026-07) is treated as a warning, not a failure, and distinct from a
# transient failure (timeout/SERVFAIL/resolver unreachable, which still counts
# as an error below): no ACCEPT rule is added for it either way, so the
# security boundary is unchanged, but treating it as fatal here would
# permanently wedge the fail-closed startup gate with no recovery short of
# editing this script.
refresh_domains() {
  local generation="$1" had_errors=0 domain ips ip dig_output
  local -a domains
  mapfile -t domains < <(build_domain_list)
  for domain in "${domains[@]}"; do
    echo "Resolving $domain..."
    # +comments (on top of +answer) surfaces the header's "status:" line
    # (NOERROR/NXDOMAIN/SERVFAIL/...) in the same single dig call, so NXDOMAIN
    # can be told apart from a transient failure below without a second
    # round-trip. `|| true`: dig itself can exit non-zero on transient
    # failures (e.g. no server reachable) before we ever look at the answer;
    # under `set -o pipefail` that would otherwise trip `set -e` and abort
    # this whole script here, before the had_errors handling below runs.
    dig_output=$(dig +noall +answer +comments +time=2 +tries=2 A "$domain" || true)
    ips=$(printf '%s\n' "$dig_output" | awk '$4 == "A" {print $5}')
    if [ -z "$ips" ]; then
      if [[ "$dig_output" =~ status:\ NXDOMAIN ]]; then
        echo "WARNING: $domain does not exist (NXDOMAIN) - skipping without failing startup (no ACCEPT rule is added either way)" >&2
      else
        echo "WARNING: failed to resolve $domain this cycle (will retry next interval)" >&2
        had_errors=1
      fi
      continue
    fi
    while read -r ip; do
      if ! add_or_touch_domain_ip "$ip" "$domain" "$generation"; then
        echo "WARNING: failed to apply rule for $domain -> $ip" >&2
        had_errors=1
      fi
    done <<<"$ips"
  done
  return "$had_errors"
}

# Deletes domain-tagged rules whose generation is older than cutoff_epoch.
# GitHub CIDR rules and the host-network rule carry no "domain=" comment and
# are never matched here. Deletes in descending line-number order since
# `iptables -D CHAIN N` renumbers everything after N once it's removed.
prune_stale_domain_rules() {
  local cutoff="$1"
  local -a stale_line_numbers=()
  local idx=0 line rule_gen
  while IFS= read -r line; do
    idx=$((idx + 1))
    if [[ "$line" =~ --comment\ \"domain=[^\;]+\;gen=([0-9]+)\" ]]; then
      rule_gen="${BASH_REMATCH[1]}"
      if (( rule_gen < cutoff )); then
        stale_line_numbers+=("$idx")
      fi
    fi
  done < <(iptables -S "$CHAIN" | tail -n +2)
  local n
  for (( n=${#stale_line_numbers[@]}-1; n>=0; n-- )); do
    iptables -D "$CHAIN" "${stale_line_numbers[n]}" 2>/dev/null || \
      echo "WARNING: failed to prune stale rule at $CHAIN line ${stale_line_numbers[n]}" >&2
  done
}

# Full startup initialization: flush, rebuild every rule from scratch,
# self-verify. Fail-closed — any error here aborts container startup.
full_init() {
  # Flush existing rules. NOTE: -F only clears rules, not the -P default policy —
  # if this script already ran once (policy is DROP from a prior run), traffic is
  # blocked immediately after this flush until rules are rebuilt below. So the
  # loopback/established/DNS-resolver ACCEPT rules are installed first, before
  # anything below that needs the network (GitHub meta read is local, but the
  # domain-resolution loop does live DNS lookups). This keeps re-running this
  # script mid-session safe: worst case during rebuild is DROP-with-DNS-only,
  # never a full lockout. CDN IP rotation is now handled by the much lighter
  # `--refresh-domains` mode (see bottom of file); a full re-run like this one
  # remains available as a heavier manual fallback (e.g. troubleshooting).
  iptables -F
  iptables -X
  iptables -t nat -F
  iptables -t nat -X
  iptables -t mangle -F
  iptables -t mangle -X

  # Allowlist chain: one ACCEPT per allowed CIDR/IP, restricted to $ALLOWED_PORTS
  # (add_cidr/add_cidr_tagged, claude-container#31). This restriction covers
  # GitHub CIDRs and the tagged per-domain rules ONLY. The DNS resolver rules
  # below and the host-network rule further down bypass CHAIN entirely (they're
  # appended straight to INPUT/OUTPUT) and stay port-unrestricted.
  iptables -N "$CHAIN"

  # Loopback and established connections
  iptables -A INPUT -i lo -j ACCEPT
  iptables -A OUTPUT -o lo -j ACCEPT
  iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
  iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

  # DNS: only to the configured resolvers (udp + tcp for large answers).
  # Installed before the domain-resolution loop below, which needs it.
  mapfile -t resolvers < <(awk '/^nameserver/ {print $2}' /etc/resolv.conf | grep -E '^[0-9.]+$' || true)
  if [ "${#resolvers[@]}" -eq 0 ]; then
    echo "WARNING: no IPv4 resolver in /etc/resolv.conf, allowing DNS to any host" >&2
    iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
    iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT
  else
    for resolver in "${resolvers[@]}"; do
      iptables -A OUTPUT -d "$resolver" -p udp --dport 53 -j ACCEPT
      iptables -A OUTPUT -d "$resolver" -p tcp --dport 53 -j ACCEPT
    done
  fi

  # GitHub IP ranges (git/gh over HTTPS and SSH). No live fetch here — that would
  # consume the unauthenticated GitHub API rate limit (60 req/h per IP) on every
  # container start. Instead this reads the snapshot claude-container's
  # stage_build_context() fetched once and baked into the image at build time —
  # the ranges change rarely enough for a stale copy to stay usable.
  local gh_meta_snapshot=/etc/claude-container/github-meta.json
  echo "Loading GitHub IP ranges from build-time snapshot..."
  local gh_ranges
  gh_ranges=$(cat "$gh_meta_snapshot" 2>/dev/null || true)
  if ! echo "$gh_ranges" | jq -e '.web and .api and .git' >/dev/null 2>&1; then
    echo "ERROR: GitHub meta snapshot at $gh_meta_snapshot is missing or invalid" >&2
    exit 1
  fi
  while read -r cidr; do
    add_cidr "$cidr" "GitHub meta"
  done < <(echo "$gh_ranges" | jq -r '(.web + .api + .git)[]' | sort -u)

  # Claude Code endpoints + project-specific domains, tagged with a generation
  # timestamp so the background --refresh-domains loop can find and expire
  # stale entries as CDN-backed domains rotate IPs.
  if ! refresh_domains "$(date +%s)"; then
    echo "ERROR: one or more domains failed to resolve during initial firewall setup" >&2
    exit 1
  fi

  # Host network (gateway only), for host-side services. Scoped to the single
  # gateway IP, not its /24 (claude-container#31) — no port restriction
  # (this bypasses CHAIN, see the note where CHAIN is created above).
  local host_ip host_network
  host_ip=$(ip route | awk '/^default/ {print $3; exit}')
  if [ -z "$host_ip" ]; then
    echo "ERROR: Failed to detect host IP" >&2
    exit 1
  fi
  host_network="${host_ip}/32"
  echo "Host network detected as: $host_network"
  iptables -A INPUT -s "$host_network" -j ACCEPT
  iptables -A OUTPUT -d "$host_network" -j ACCEPT

  # Default deny + allowlist chain; REJECT tail for immediate feedback
  iptables -P INPUT DROP
  iptables -P FORWARD DROP
  iptables -P OUTPUT DROP
  iptables -A OUTPUT -j "$CHAIN"
  iptables -A OUTPUT -j REJECT --reject-with icmp-admin-prohibited

  # IPv6 handling:
  #   1) Primary control: compose.yml's sysctls (net.ipv6.conf.*.disable_ipv6=1) should
  #      already have disabled IPv6 before this script runs, fixing a bug where glibc's
  #      getaddrinfo(AI_ADDRCONFIG) misreports IPv6 as available from a link-local-only
  #      address (no default route) and Happy Eyeballs then stalls on unreachable AAAA
  #      candidates for allowlisted CDN domains (observed 2026-07 with
  #      cyberjapandata.gsi.go.jp behind CloudFront).
  #   2) Fallback (this block): retry the same disable via /proc/sys, in case the compose
  #      sysctls setting didn't apply (e.g. older podman-compose without `sysctls:`
  #      support). Non-fatal — this is a reliability fix, not the security gate, so it
  #      deliberately breaks from this script's usual fail-closed rule.
  #   3) Security boundary (unchanged below): drop all IPv6 via ip6tables regardless of
  #      whether 1)/2) succeeded. The allowlist only resolves A records, so any
  #      surviving IPv6 path would otherwise bypass it entirely.
  disable_ipv6_fallback() {
    local path ok=1
    for path in /proc/sys/net/ipv6/conf/*/disable_ipv6; do
      [ -e "$path" ] || continue
      echo 1 > "$path" 2>/dev/null || ok=0
    done
    [ "$ok" -eq 1 ]
  }
  if disable_ipv6_fallback; then
    echo "IPv6 disabled via /proc/sys (fallback check passed; compose.yml sysctls is primary)"
  else
    echo "WARNING: could not disable IPv6 via /proc/sys/net/ipv6/conf/*/disable_ipv6 (fallback)." >&2
    echo "WARNING: if compose.yml sysctls also failed to apply, glibc may still prefer AAAA" >&2
    echo "WARNING: records for allowlisted CDN domains, risking intermittent Happy-Eyeballs" >&2
    echo "WARNING: failures. The ip6tables DROP below remains the active security boundary." >&2
  fi

  # IPv6: drop everything except loopback (allowlist is IPv4-only; security boundary,
  # independent of whether the disable_ipv6 sysctl above took effect)
  if ip6tables -L >/dev/null 2>&1; then
    ip6tables -F
    ip6tables -X
    ip6tables -A INPUT -i lo -j ACCEPT
    ip6tables -A OUTPUT -o lo -j ACCEPT
    ip6tables -P INPUT DROP
    ip6tables -P FORWARD DROP
    ip6tables -P OUTPUT DROP
  else
    echo "ip6tables unavailable, assuming no IPv6 connectivity"
  fi

  echo "Firewall configuration complete"
  echo "Verifying firewall rules..."
  if curl --connect-timeout 5 -s https://example.com >/dev/null 2>&1; then
    echo "ERROR: Firewall verification failed - was able to reach https://example.com" >&2
    exit 1
  fi
  echo "Verification passed - unable to reach https://example.com as expected"
  # TCP connect only (no HTTP request) so verification doesn't consume the
  # unauthenticated GitHub API rate limit on every container start.
  if ! timeout 10 bash -c 'exec 3<>/dev/tcp/api.github.com/443' 2>/dev/null; then
    echo "ERROR: Firewall verification failed - unable to reach api.github.com:443" >&2
    exit 1
  fi
  echo "Verification passed - able to reach api.github.com:443 as expected"
  if ! curl --connect-timeout 10 -s -o /dev/null https://api.anthropic.com; then
    echo "ERROR: Firewall verification failed - unable to reach https://api.anthropic.com" >&2
    exit 1
  fi
  echo "Verification passed - able to reach https://api.anthropic.com as expected"
  # Confirm the port restriction (claude-container#31) actually blocks a
  # non-allowed port on an otherwise-allowed IP. github.com genuinely listens
  # on port 80 (HTTP -> HTTPS redirect), so a failure here can't be confused
  # with "the remote wasn't listening" — it has to be our own rule rejecting
  # it. This only exercises the CHAIN-scoped restriction (GitHub CIDRs /
  # tagged domain rules); DNS(53) and the host-network rule bypass CHAIN
  # entirely and are not covered by this check.
  if timeout 5 bash -c 'exec 3<>/dev/tcp/api.github.com/80' 2>/dev/null; then
    echo "ERROR: Firewall verification failed - was able to reach api.github.com:80 (port restriction not enforced)" >&2
    exit 1
  fi
  echo "Verification passed - unable to reach api.github.com:80 as expected (port restriction enforced)"
}

# Lightweight periodic touch-up: re-resolves every allowed domain, adds any
# newly-seen IPs, refreshes the generation tag on IPs still in rotation, and
# prunes IPs not seen for GRACE_WINDOW_SECONDS. No flush, no policy changes,
# no self-verification — assumes full_init already ran successfully once
# (entrypoint.sh only starts the background refresh loop after that). Runs
# fail-open: a failed cycle logs a warning and lets the next tick retry,
# rather than tearing down the container.
do_refresh() {
  local gen
  gen="$(date +%s)"
  echo "--- refresh cycle $(date -Is) ---"
  refresh_domains "$gen" || echo "WARNING: one or more domains failed to refresh this cycle" >&2
  prune_stale_domain_rules "$(( gen - GRACE_WINDOW_SECONDS ))"
}

case "$MODE" in
  init) full_init ;;
  refresh) do_refresh ;;
esac
