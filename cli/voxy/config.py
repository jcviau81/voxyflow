"""Configuration: base URL and auth token resolution."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_URL = "http://localhost:8000"
TOKEN_PATH = Path.home() / ".voxyflow" / "auth_token"
CLI_CONFIG_PATH = Path.home() / ".voxyflow" / "cli.json"

# Refs that force the general/main chat even when a default workspace is set.
GENERAL_REFS = {"general", "main", "home", "none"}


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


# -- persistent CLI config (`voxy use`) ---------------------------------

def load_cli_config(path: Path | None = None) -> dict:
    """Read ~/.voxyflow/cli.json (empty dict when missing or corrupt)."""
    p = path if path is not None else CLI_CONFIG_PATH
    try:
        import json

        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cli_config(cfg: dict, path: Path | None = None) -> None:
    import json

    p = path if path is not None else CLI_CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2) + "\n")


def get_default_workspace(path: Path | None = None) -> dict | None:
    """The persisted default workspace ({'id', 'title'}) or None."""
    ws = load_cli_config(path).get("workspace")
    return ws if isinstance(ws, dict) and ws.get("id") else None


def set_default_workspace(ws_id: str, title: str, path: Path | None = None) -> None:
    cfg = load_cli_config(path)
    cfg["workspace"] = {"id": ws_id, "title": title}
    save_cli_config(cfg, path)


def clear_default_workspace(path: Path | None = None) -> None:
    cfg = load_cli_config(path)
    cfg.pop("workspace", None)
    save_cli_config(cfg, path)


def effective_workspace_ref(
    option_value: str | None, default_ws: dict | None
) -> str | None:
    """Resolve which workspace ref a command should use.

    Explicit ``-w`` wins; the refs in GENERAL_REFS force the general chat
    (ref None); otherwise the persisted default applies.
    """
    if option_value:
        if option_value.strip().lower() in GENERAL_REFS:
            return None
        return option_value
    if default_ws:
        return default_ws["id"]
    return None


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
