"""Bearer-token auth for destructive / secret-writing endpoints.

Threat model
============
Voxyflow is designed for single-user local (or Tailscale-only) deployment. The
**first** line of defense is network confinement — bind the backend to
loopback/Tailscale and keep Caddy off the public internet. This bearer token is
a defense-in-depth layer on top of that. It is **not** sufficient by itself for
public-internet exposure.

What it blocks
--------------
- A misconfigured rebind (``--host 0.0.0.0``) on a LAN: random scanners can hit
  /api/settings PUT and exfiltrate API keys without going through the frontend.
- Another Tailscale peer on the same mesh poking at the API without using the UI.
- A malicious same-mesh page doing CSRF-style writes — CORS blocks it from
  reading the bootstrap token, so it can't forge authed writes.

Storage
-------
Token lives in ``~/.voxyflow/auth_token`` with 0600 perms. Generated on first
use with ``secrets.token_urlsafe(32)`` (~256 bits of entropy). Delete the file
to rotate — the backend will mint a new one on the next request.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)

_TOKEN_FILE = Path(
    os.environ.get("VOXYFLOW_DATA", os.path.expanduser("~/.voxyflow"))
) / "auth_token"

_cached_token: str | None = None


def _load_or_create_token() -> str:
    """Return the bearer token, generating + persisting it on first use."""
    global _cached_token
    if _cached_token:
        return _cached_token

    _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)

    if _TOKEN_FILE.exists():
        try:
            existing = _TOKEN_FILE.read_text(encoding="utf-8").strip()
        except OSError as e:
            logger.warning("auth_service: failed to read token file (%s), regenerating", e)
            existing = ""
        if existing:
            _cached_token = existing
            return _cached_token

    new_token = secrets.token_urlsafe(32)
    _TOKEN_FILE.write_text(new_token, encoding="utf-8")
    try:
        os.chmod(_TOKEN_FILE, 0o600)
    except OSError as e:
        logger.warning("auth_service: could not chmod 0600 on %s: %s", _TOKEN_FILE, e)
    _cached_token = new_token
    logger.info("auth_service: generated new bearer token at %s", _TOKEN_FILE)
    return _cached_token


def get_auth_token() -> str:
    """Public accessor — used by /api/auth/bootstrap to hand the token to the UI."""
    return _load_or_create_token()


async def verify_auth(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency — reject requests without a valid bearer token.

    Accepts ``Authorization: Bearer <token>``. Uses ``secrets.compare_digest``
    to avoid timing leaks.
    """
    expected = _load_or_create_token()
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing Authorization header.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token.strip(), expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid auth token.")
