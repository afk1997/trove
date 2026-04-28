from __future__ import annotations
import ipaddress
import socket
from urllib.parse import urlparse


_ALLOWED_SCHEMES = {"http", "https"}

# RFC1918 + loopback + link-local + reserved ranges we never want to hit.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network(net) for net in [
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
        "0.0.0.0/8",
        "100.64.0.0/10",
    ]
]


def _is_blocked_ip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in _BLOCKED_NETWORKS)


def is_safe_url(url: str) -> bool:
    """Return True only if url is a public http(s) URL we're willing to fetch.

    Rejects: non-http schemes, anything beginning with '-' (CLI option-shaped),
    private/loopback/link-local IPs, hostnames that resolve to those.
    """
    if not url or not isinstance(url, str):
        return False
    s = url.strip()
    if not s:
        return False
    # Refuse anything that looks like a CLI option — guards against argv injection
    # even though we also use `--` separator at the subprocess layer.
    if s.startswith("-"):
        return False
    try:
        parsed = urlparse(s)
    except ValueError:
        return False
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False
    host = parsed.hostname
    if not host:
        return False
    host = host.lower()
    if host in {"localhost", "ip6-localhost", "ip6-loopback"}:
        return False
    # If host is a bare IP literal, check it directly.
    if _is_blocked_ip(host):
        return False
    # Otherwise resolve and check every returned address.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Unresolvable — let yt-dlp surface the network error rather than block here.
        return True
    for info in infos:
        addr = info[4][0]
        if _is_blocked_ip(addr):
            return False
    return True
