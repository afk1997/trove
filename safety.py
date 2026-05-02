from __future__ import annotations
import hmac
import hashlib
import ipaddress
import socket
from urllib.parse import urlparse
import os
from functools import wraps
from flask import request, jsonify, g
import time
from collections import deque
from threading import Lock
import secrets


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


def token_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        token = os.environ.get("TROVE_TOKEN", "").strip()
        if not token:
            return view(*args, **kwargs)
        header = request.headers.get("Authorization", "")
        if header == f"Bearer {token}":
            return view(*args, **kwargs)
        return jsonify({"error": "unauthorized"}), 401
    return wrapper


def sign_resource(resource_id: str) -> str:
    """Return an HMAC-SHA256 sig for `resource_id` keyed by TROVE_TOKEN.

    Used to authenticate media URLs embedded in pages where the browser
    can't attach an Authorization header (e.g. <video src>). Returns an
    empty string when TROVE_TOKEN is unset (no signature needed).
    """
    token = os.environ.get("TROVE_TOKEN", "").strip()
    if not token:
        return ""
    return hmac.new(token.encode(), resource_id.encode(), hashlib.sha256).hexdigest()


def verify_resource_sig(resource_id: str, sig: str) -> bool:
    """Constant-time check against the expected signature for resource_id."""
    expected = sign_resource(resource_id)
    if not expected:
        return False
    return hmac.compare_digest(expected, sig or "")


def token_or_sig_required(view):
    """Like token_required, but ALSO accepts a `?sig=…` query param signed by sign_resource.

    Use on routes whose URL gets embedded in publicly-rendered HTML
    (e.g. /api/file/<id> as a <video src>). The view handler must accept
    the resource id as the FIRST positional argument so we can verify
    the signature against it.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        token = os.environ.get("TROVE_TOKEN", "").strip()
        if not token:
            return view(*args, **kwargs)
        header = request.headers.get("Authorization", "")
        if header == f"Bearer {token}":
            return view(*args, **kwargs)
        # Accept signed URL: extract the resource id from the route kwargs
        sig = request.args.get("sig", "")
        # Find the first kwarg that's the resource id (Flask passes route
        # vars as kwargs). We accept any string-typed kwarg.
        for v in kwargs.values():
            if isinstance(v, str) and verify_resource_sig(v, sig):
                return view(*args, **kwargs)
        return jsonify({"error": "unauthorized"}), 401
    return wrapper


class RateLimiter:
    """Sliding-window per-key rate limiter. In-process only."""

    def __init__(self, rate: int, per_seconds: int):
        self.rate = rate
        self.per_seconds = per_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        if self.rate <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            cutoff = now - self.per_seconds
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.rate:
                return False
            q.append(now)
            return True


def attach_security_headers(app):
    """Mount per-request CSP nonce + standard security headers on a Flask app."""

    @app.before_request
    def _set_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.after_request
    def _set_headers(response):
        nonce = getattr(g, "csp_nonce", "")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"img-src 'self' https: data:; "
            f"style-src 'self' 'nonce-{nonce}' https://fonts.googleapis.com; "
            f"font-src 'self' https://fonts.gstatic.com; "
            f"script-src 'self' 'nonce-{nonce}'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        return response

    return app
