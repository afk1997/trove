"""Tests for config.py — defaults + the unauthenticated public-bind guard."""
from __future__ import annotations

import importlib

import pytest

import config


def test_defaults_are_localhost_8899(monkeypatch):
    # Reload with a clean env so module-level defaults pick up the right values.
    for k in ("HOST", "PORT", "TROVE_URL"):
        monkeypatch.delenv(k, raising=False)
    cfg = importlib.reload(config)
    try:
        assert cfg.DEFAULT_HOST == "127.0.0.1"
        assert cfg.DEFAULT_PORT == 8899
        assert cfg.DEFAULT_BASE_URL == "http://127.0.0.1:8899"
    finally:
        importlib.reload(config)


def test_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.delenv("TROVE_URL", raising=False)
    cfg = importlib.reload(config)
    try:
        assert cfg.DEFAULT_HOST == "0.0.0.0"
        assert cfg.DEFAULT_PORT == 9000
        assert cfg.DEFAULT_BASE_URL == "http://0.0.0.0:9000"
    finally:
        importlib.reload(config)


def test_trove_url_overrides_host_port(monkeypatch):
    monkeypatch.setenv("TROVE_URL", "https://trove.example.com")
    cfg = importlib.reload(config)
    try:
        assert cfg.DEFAULT_BASE_URL == "https://trove.example.com"
    finally:
        importlib.reload(config)


# ----- assert_safe_bind --------------------------------------------------

def test_loopback_bind_always_allowed():
    for host in ("127.0.0.1", "::1", "localhost"):
        config.assert_safe_bind(host, env={})


def test_public_bind_without_token_refused():
    with pytest.raises(config.UnauthenticatedPublicBindError):
        config.assert_safe_bind("0.0.0.0", env={})


def test_public_bind_with_token_allowed():
    config.assert_safe_bind("0.0.0.0", env={"TROVE_TOKEN": "secret"})


def test_public_bind_with_explicit_optin_allowed():
    config.assert_safe_bind("0.0.0.0", env={"TROVE_ALLOW_UNAUTH_PUBLIC": "1"})


def test_optin_must_be_exactly_1():
    # Anything other than "1" should NOT count as opt-in — prevents typos
    # like TROVE_ALLOW_UNAUTH_PUBLIC=true silently disabling the guard.
    for v in ("true", "yes", "0", "", "TRUE"):
        with pytest.raises(config.UnauthenticatedPublicBindError):
            config.assert_safe_bind("0.0.0.0", env={"TROVE_ALLOW_UNAUTH_PUBLIC": v})


def test_empty_token_does_not_count():
    with pytest.raises(config.UnauthenticatedPublicBindError):
        config.assert_safe_bind("0.0.0.0", env={"TROVE_TOKEN": "   "})


def test_arbitrary_public_address_refused():
    # Any non-loopback bind triggers the guard, not just 0.0.0.0.
    with pytest.raises(config.UnauthenticatedPublicBindError):
        config.assert_safe_bind("192.168.1.10", env={})


def test_error_message_lists_three_remedies():
    try:
        config.assert_safe_bind("0.0.0.0", env={})
    except config.UnauthenticatedPublicBindError as e:
        msg = str(e)
        assert "HOST=127.0.0.1" in msg
        assert "TROVE_TOKEN" in msg
        assert "TROVE_ALLOW_UNAUTH_PUBLIC" in msg
    else:
        pytest.fail("expected UnauthenticatedPublicBindError")
