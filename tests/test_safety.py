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
