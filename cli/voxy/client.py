"""Thin HTTP client for the Voxyflow REST API with friendly error handling."""

from __future__ import annotations

import json
from typing import Any

import httpx
import typer
from rich.console import Console

from .config import get_base_url, load_token

err_console = Console(stderr=True)


class CliError(Exception):
    """A user-facing CLI error — printed as a single line, no traceback."""


def die(message: str) -> "typer.Exit":
    """Print a one-line error and return an Exit to raise."""
    err_console.print(f"[red]error:[/red] {message}")
    return typer.Exit(code=1)


class VoxyClient:
    """Synchronous Voxyflow API client.

    All request methods return parsed JSON and convert transport / HTTP
    errors into single-line :class:`CliError` messages.
    """

    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or get_base_url()).rstrip("/")
        self._token = token
        self._client: httpx.Client | None = None

    # -- lifecycle -----------------------------------------------------
    def _http(self) -> httpx.Client:
        if self._client is None:
            if self._token is None:
                try:
                    self._token = load_token(self.base_url)
                except httpx.ConnectError:
                    raise CliError(
                        f"cannot reach Voxyflow backend at {self.base_url} — is it running?"
                    )
                except Exception as exc:  # bootstrap failure
                    raise CliError(f"could not obtain auth token: {exc}")
            self._client = httpx.Client(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=30.0,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def __enter__(self) -> "VoxyClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- requests ------------------------------------------------------
    def request(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = self._http().request(method, path, **kwargs)
        except httpx.ConnectError:
            raise CliError(
                f"cannot reach Voxyflow backend at {self.base_url} — is it running?"
            )
        except httpx.TimeoutException:
            raise CliError(f"request to {self.base_url}{path} timed out")
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("detail", "")
            except Exception:
                detail = resp.text[:200]
            raise CliError(f"{method} {path} → HTTP {resp.status_code}: {detail}")
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except json.JSONDecodeError:
            raise CliError(f"{method} {path} returned non-JSON response")

    def get(self, path: str, **kwargs) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> Any:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs) -> Any:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs) -> Any:
        return self.request("DELETE", path, **kwargs)


# -- workspace resolution (pure, unit-testable) -------------------------

def resolve_workspace(workspaces: list[dict], ref: str) -> dict:
    """Resolve a workspace reference (id or title, case-insensitive) to a dict.

    Raises :class:`CliError` when not found or ambiguous.
    """
    ref = ref.strip()
    for ws in workspaces:
        if ws.get("id") == ref:
            return ws
    lowered = ref.lower()
    matches = [ws for ws in workspaces if (ws.get("title") or "").lower() == lowered]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        ids = ", ".join(ws["id"] for ws in matches)
        raise CliError(f"workspace name {ref!r} is ambiguous (ids: {ids}) — use the id")
    # Fall back to unique title prefix match for convenience.
    prefix = [ws for ws in workspaces if (ws.get("title") or "").lower().startswith(lowered)]
    if len(prefix) == 1:
        return prefix[0]
    raise CliError(f"workspace {ref!r} not found (try `voxy ws list`)")


def get_workspace(client: VoxyClient, ref: str) -> dict:
    """List workspaces from the API and resolve ``ref`` against them."""
    return resolve_workspace(client.get("/api/workspaces"), ref)
