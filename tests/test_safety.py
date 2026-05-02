import pytest
from safety import is_safe_url


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "http://vimeo.com/123",
    "https://www.tiktok.com/@user/video/1234",
])
def test_is_safe_url_accepts_public(url):
    assert is_safe_url(url) is True


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "http://localhost:8899/",
    "http://127.0.0.1/",
    "http://10.0.0.1/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "ftp://example.com/foo",
    "javascript:alert(1)",
    "--exec=touch /tmp/pwned",
    "-o /etc/whatever",
    "",
    "not a url",
])
def test_is_safe_url_rejects_unsafe(url):
    assert is_safe_url(url) is False


import os
from typing import Optional
from flask import Flask
from safety import token_required


def _make_app(token: Optional[str]):
    app = Flask(__name__)
    if token is not None:
        os.environ["TROVE_TOKEN"] = token
    else:
        os.environ.pop("TROVE_TOKEN", None)

    @app.get("/secret")
    @token_required
    def secret():
        return "ok"

    return app


def test_token_required_off_by_default():
    app = _make_app(None)
    client = app.test_client()
    assert client.get("/secret").status_code == 200


def test_token_required_rejects_missing_header():
    app = _make_app("hunter2")
    client = app.test_client()
    assert client.get("/secret").status_code == 401


def test_token_required_rejects_wrong_token():
    app = _make_app("hunter2")
    client = app.test_client()
    r = client.get("/secret", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_token_required_accepts_correct_token():
    app = _make_app("hunter2")
    client = app.test_client()
    r = client.get("/secret", headers={"Authorization": "Bearer hunter2"})
    assert r.status_code == 200


import time
from safety import RateLimiter


def test_rate_limiter_allows_under_cap():
    rl = RateLimiter(rate=5, per_seconds=60)
    for _ in range(5):
        assert rl.allow("1.2.3.4") is True


def test_rate_limiter_blocks_over_cap():
    rl = RateLimiter(rate=3, per_seconds=60)
    for _ in range(3):
        assert rl.allow("1.2.3.4") is True
    assert rl.allow("1.2.3.4") is False


def test_rate_limiter_per_ip_isolated():
    rl = RateLimiter(rate=2, per_seconds=60)
    assert rl.allow("1.1.1.1") is True
    assert rl.allow("1.1.1.1") is True
    assert rl.allow("1.1.1.1") is False
    assert rl.allow("2.2.2.2") is True


def test_rate_limiter_window_resets(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("safety.time.monotonic", lambda: now[0])
    rl = RateLimiter(rate=2, per_seconds=10)
    assert rl.allow("x") is True
    assert rl.allow("x") is True
    assert rl.allow("x") is False
    now[0] = 11.0
    assert rl.allow("x") is True


from safety import attach_security_headers


def test_attach_security_headers_sets_basic_headers():
    app = Flask(__name__)
    attach_security_headers(app)

    @app.get("/")
    def hello():
        return "hi"

    r = app.test_client().get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "X-Frame-Options" not in r.headers
    assert r.headers["Referrer-Policy"] == "no-referrer"
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    # Locked-down clickjacking guard: arbitrary origins must NOT be
    # allowed to embed the app in an <iframe>.
    assert "frame-ancestors 'none'" in csp
    assert "frame-ancestors *" not in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]


def test_attach_security_headers_includes_per_request_nonce():
    app = Flask(__name__)
    attach_security_headers(app)

    @app.get("/")
    def hello():
        from flask import g
        return g.csp_nonce

    client = app.test_client()
    r1 = client.get("/")
    r2 = client.get("/")
    nonce1 = r1.get_data(as_text=True)
    nonce2 = r2.get_data(as_text=True)
    assert nonce1 and nonce2 and nonce1 != nonce2
    assert f"'nonce-{nonce1}'" in r1.headers["Content-Security-Policy"]
