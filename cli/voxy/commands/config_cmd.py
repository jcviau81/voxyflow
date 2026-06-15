"""`voxy config` — view and edit Voxyflow settings over the REST API.

Settings are a single document (GET/PUT /api/settings). `set` does a
read-modify-write of the full document; api_key fields arrive redacted as
`***` and the backend preserves the real values on save.
"""

from __future__ import annotations

import json
from typing import Any

import typer

from ..client import CliError, VoxyClient, die
from ..output import console, print_json

app = typer.Typer(help="View and edit Voxyflow settings.", no_args_is_help=True)


# -- pure helpers (unit-tested offline) ----------------------------------

def parse_value(raw: str) -> Any:
    """JSON when it parses ('true' → True, '5' → 5, '[..]' → list), else string."""
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _descend(cur: Any, part: str, path: str) -> Any:
    if isinstance(cur, list):
        try:
            idx = int(part)
        except ValueError:
            raise CliError(f"{path!r}: {part!r} is not a list index (0..{len(cur) - 1})")
        if not 0 <= idx < len(cur):
            raise CliError(f"{path!r}: index {idx} out of range (list has {len(cur)} items)")
        return cur[idx]
    if isinstance(cur, dict):
        if part not in cur:
            known = ", ".join(sorted(cur)[:12]) or "none"
            raise CliError(f"{path!r}: unknown key {part!r} (known: {known})")
        return cur[part]
    raise CliError(f"{path!r}: cannot descend into a {type(cur).__name__} at {part!r}")


def get_path(data: Any, path: str) -> Any:
    """Resolve a dotted path (dict keys and list indices) in a settings doc."""
    cur = data
    for part in path.split("."):
        cur = _descend(cur, part, path)
    return cur


def set_path(data: Any, path: str, value: Any) -> Any:
    """Set a dotted path in place, returning the previous value.

    The leaf key must already exist — settings are a fixed schema and the
    backend silently drops unknown keys, so a typo would otherwise no-op.
    """
    parts = path.split(".")
    parent = data
    for part in parts[:-1]:
        parent = _descend(parent, part, path)
    old = _descend(parent, parts[-1], path)
    if isinstance(old, (dict, list)) and not isinstance(value, type(old)):
        raise CliError(
            f"{path!r} is a {type(old).__name__} — pass a JSON {type(old).__name__} "
            f"or set one of its fields instead"
        )
    if isinstance(parent, list):
        parent[int(parts[-1])] = value
    else:
        parent[parts[-1]] = value
    return old


def _fmt_leaf(value: Any) -> str:
    return json.dumps(value) if isinstance(value, (dict, list)) else str(value)


# -- commands ------------------------------------------------------------

@app.command("show")
def show(
    as_json: bool = typer.Option(False, "--json", help="Plain JSON for scripting."),
):
    """Show all settings (secrets redacted as ***)."""
    try:
        with VoxyClient() as client:
            settings = client.get("/api/settings")
    except CliError as e:
        raise die(str(e))
    if as_json:
        print_json(settings)
    else:
        console.print_json(data=settings)


@app.command("get")
def get(
    path: str = typer.Argument(..., help="Dotted path, e.g. models.fast.model"),
):
    """Read one settings value by dotted path."""
    try:
        with VoxyClient() as client:
            settings = client.get("/api/settings")
        value = get_path(settings, path)
    except CliError as e:
        raise die(str(e))
    if isinstance(value, (dict, list)):
        print_json(value)
    else:
        print(value)


@app.command("set")
def set_(
    path: str = typer.Argument(..., help="Dotted path, e.g. models.fast.model"),
    value: str = typer.Argument(..., help="New value (JSON parsed when possible)."),
):
    """Set one settings value by dotted path (read-modify-write)."""
    try:
        with VoxyClient() as client:
            settings = client.get("/api/settings")
            old = set_path(settings, path, parse_value(value))
            client.request("PUT", "/api/settings", json=settings)
    except CliError as e:
        raise die(str(e))
    console.print(
        f"[green]Saved[/green] {path}: [dim]{_fmt_leaf(old)}[/dim] → [bold]{value}[/bold]"
    )
    if old == "***":
        console.print("[dim](previous value was a redacted secret — now replaced)[/dim]")
