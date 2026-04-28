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
