"""Configuration: base URL and auth token resolution."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_URL = "http://localhost:8000"
TOKEN_PATH = Path.home() / ".voxyflow" / "auth_token"


def get_base_url() -> str:
    """Backend base URL — VOXYFLOW_URL env var, default http://localhost:8000."""
    return os.environ.get("VOXYFLOW_URL", DEFAULT_URL).rstrip("/")


def ws_url(base_url: str) -> str:
    """Derive the websocket URL from the HTTP base URL."""
    if base_url.startswith("https://"):
        return "wss://" + base_url[len("https://"):] + "/ws"
    if base_url.startswith("http://"):
        return "ws://" + base_url[len("http://"):] + "/ws"
    return base_url.rstrip("/") + "/ws"


def load_token(
    base_url: str | None = None,
    token_path: Path | None = None,
    http_get=None,
) -> str:
    """Resolve the auth token.

    Order: ``~/.voxyflow/auth_token`` file, then the ``/api/auth/bootstrap``
    endpoint (caching the result back to the file with mode 0600).

    ``http_get`` is injectable for tests; defaults to ``httpx.get``.
    """
    path = token_path if token_path is not None else TOKEN_PATH
    try:
        token = path.read_text().strip()
        if token:
            return token
    except OSError:
        pass

    if http_get is None:
        import httpx

        http_get = httpx.get

    url = (base_url or get_base_url()).rstrip("/") + "/api/auth/bootstrap"
    resp = http_get(url, timeout=10.0)
    resp.raise_for_status()
    token = resp.json().get("token", "")
    if not token:
        raise RuntimeError(f"No token returned by {url}")

    # Cache for next time (best-effort).
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token + "\n")
        path.chmod(0o600)
    except OSError:
        pass
    return token
