"""Single source of truth for Trove host/port/base-URL defaults.

Historically these defaults drifted across entrypoints (app.py used
``0.0.0.0:5000``, cli/mcp used ``127.0.0.1:5000``, README/Dockerfile/
trove.sh used ``127.0.0.1:8899``). That was both a UX bug (CLI
talking to the wrong port out of the box) and a security footgun
(Flask runner binding to ``0.0.0.0`` with no token by default while
the README promised localhost-only).

Everything that needs a host, port, or base URL imports from here.
"""
from __future__ import annotations

import os


DEFAULT_HOST: str = os.environ.get("HOST", "127.0.0.1")
DEFAULT_PORT: int = int(os.environ.get("PORT", "8899"))
DEFAULT_BASE_URL: str = os.environ.get(
    "TROVE_URL",
    f"http://{DEFAULT_HOST}:{DEFAULT_PORT}",
)


class UnauthenticatedPublicBindError(RuntimeError):
    """Raised when the server would bind to a non-loopback address with
    no TROVE_TOKEN set and no explicit opt-in via TROVE_ALLOW_UNAUTH_PUBLIC=1.

    Refusing to start protects users from accidentally exposing an
    unauthenticated download/transcribe API to their LAN or, worse,
    the public internet.
    """


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def assert_safe_bind(host: str, *, env: dict[str, str] | None = None) -> None:
    """Raise if `host` would expose Trove publicly without a token.

    Allows the bind when ANY of the following is true:
      * host is loopback (127.0.0.1, ::1, localhost)
      * TROVE_TOKEN is set (every /api/* request must authenticate)
      * TROVE_ALLOW_UNAUTH_PUBLIC=1 (explicit opt-in for trusted LANs,
        Docker port-forwarding without auth, kiosks, etc.)

    `env` is injectable for unit tests; defaults to os.environ.
    """
    e = env if env is not None else os.environ
    if host in _LOOPBACK:
        return
    if (e.get("TROVE_TOKEN") or "").strip():
        return
    if (e.get("TROVE_ALLOW_UNAUTH_PUBLIC") or "").strip() == "1":
        return
    raise UnauthenticatedPublicBindError(
        f"Refusing to bind to {host!r} without authentication.\n"
        "Trove's HTTP API has no auth by default; binding to a non-\n"
        "loopback address would expose downloads/transcripts to anyone\n"
        "who can reach the port.\n\n"
        "Pick ONE:\n"
        "  1. Bind to localhost only:   export HOST=127.0.0.1\n"
        "  2. Require a bearer token:   export TROVE_TOKEN=$(openssl rand -hex 32)\n"
        "  3. Acknowledge the risk:     export TROVE_ALLOW_UNAUTH_PUBLIC=1\n"
        "     (only safe on a trusted LAN or behind a private network)"
    )
