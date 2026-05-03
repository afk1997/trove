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


# ---------------------------------------------------------------------------
# Signed-URL system: scope, expiry, and decorator-factory verification.
# ---------------------------------------------------------------------------
import safety
from safety import (
    sign_resource, verify_signature, signed_query,
    token_or_sig_required,
    SCOPE_MEDIA, SCOPE_TRANSCRIPT_VIEW, SCOPE_TRANSCRIPT_EXPORT,
)


def test_sign_resource_returns_empty_when_token_unset(monkeypatch):
    monkeypatch.delenv("TROVE_TOKEN", raising=False)
    sig, exp = sign_resource("abc", SCOPE_MEDIA)
    assert sig == "" and exp == 0
    # signed_query mirrors the empty contract so templates can splice
    # the result unconditionally.
    assert signed_query("abc", SCOPE_MEDIA) == ""


def test_sign_and_verify_roundtrip(monkeypatch):
    monkeypatch.setenv("TROVE_TOKEN", "hunter2")
    sig, exp = sign_resource("abc", SCOPE_MEDIA, expires_in=60)
    assert sig and exp > int(time.time())
    assert verify_signature("abc", SCOPE_MEDIA, sig, exp) is True


def test_verify_rejects_expired_sig(monkeypatch):
    """A sig minted in the past must verify False even when otherwise valid."""
    monkeypatch.setenv("TROVE_TOKEN", "hunter2")
    sig, exp = sign_resource("abc", SCOPE_MEDIA, expires_in=60)
    # Jump the clock 1h past expiry.
    real_time = time.time
    monkeypatch.setattr(safety.time, "time", lambda: real_time() + 3700)
    assert verify_signature("abc", SCOPE_MEDIA, sig, exp) is False


def test_verify_rejects_cross_scope_replay(monkeypatch):
    """A sig minted under one scope must NOT verify under another."""
    monkeypatch.setenv("TROVE_TOKEN", "hunter2")
    sig, exp = sign_resource("abc", SCOPE_MEDIA, expires_in=60)
    assert verify_signature("abc", SCOPE_TRANSCRIPT_EXPORT, sig, exp) is False
    assert verify_signature("abc", SCOPE_TRANSCRIPT_VIEW,   sig, exp) is False


def test_verify_rejects_cross_resource_replay(monkeypatch):
    """A sig for resource A must NOT verify for resource B (same scope)."""
    monkeypatch.setenv("TROVE_TOKEN", "hunter2")
    sig, exp = sign_resource("abc", SCOPE_MEDIA, expires_in=60)
    assert verify_signature("xyz", SCOPE_MEDIA, sig, exp) is False


def test_verify_rejects_missing_or_garbage_exp(monkeypatch):
    monkeypatch.setenv("TROVE_TOKEN", "hunter2")
    sig, _ = sign_resource("abc", SCOPE_MEDIA, expires_in=60)
    assert verify_signature("abc", SCOPE_MEDIA, sig, "")            is False
    assert verify_signature("abc", SCOPE_MEDIA, sig, "not-a-number") is False
    assert verify_signature("abc", SCOPE_MEDIA, sig, None)           is False  # type: ignore[arg-type]


def test_verify_rejects_when_token_unset(monkeypatch):
    """Even a structurally-valid sig must verify False with no token,
    because TROVE_TOKEN being unset means the whole bearer system is
    off — mistakenly accepting a sig in that mode would amount to a
    permanent bypass."""
    monkeypatch.setenv("TROVE_TOKEN", "hunter2")
    sig, exp = sign_resource("abc", SCOPE_MEDIA, expires_in=60)
    monkeypatch.delenv("TROVE_TOKEN", raising=False)
    assert verify_signature("abc", SCOPE_MEDIA, sig, exp) is False


def test_sign_resource_unknown_scope_raises(monkeypatch):
    monkeypatch.setenv("TROVE_TOKEN", "hunter2")
    with pytest.raises(ValueError):
        sign_resource("abc", "made-up-scope")


def test_decorator_factory_only_verifies_named_kwarg(monkeypatch):
    """Regression: the old decorator accepted "any string kwarg" so an
    export route's ``fmt`` parameter could (theoretically) be misread
    as the resource id. The new factory must verify ONLY the named
    kwarg — a sig minted for the wrong kwarg's value must not unlock."""
    monkeypatch.setenv("TROVE_TOKEN", "hunter2")
    monkeypatch.setenv("TROVE_RATE_LIMIT", "0")
    app = Flask(__name__)

    @app.get("/r/<rid>/<fmt>")
    @token_or_sig_required(SCOPE_TRANSCRIPT_EXPORT, kwarg="rid")
    def view(rid, fmt):
        return f"{rid}:{fmt}"

    c = app.test_client()
    # Sig minted against rid → 200
    sig, exp = sign_resource("R1", SCOPE_TRANSCRIPT_EXPORT, expires_in=60)
    assert c.get(f"/r/R1/srt?sig={sig}&exp={exp}").status_code == 200
    # Sig minted against the OTHER kwarg's value (fmt) must NOT unlock.
    bad_sig, bad_exp = sign_resource("srt", SCOPE_TRANSCRIPT_EXPORT, expires_in=60)
    assert c.get(f"/r/R1/srt?sig={bad_sig}&exp={bad_exp}").status_code == 401


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
