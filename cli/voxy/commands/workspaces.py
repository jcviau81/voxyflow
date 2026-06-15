"""`voxy ws` — workspace commands."""

from __future__ import annotations

import typer
from rich.table import Table

from ..client import CliError, VoxyClient, die, get_workspace
from ..config import get_default_workspace
from ..output import console, fmt_age, fmt_status, print_json

app = typer.Typer(help="Manage workspaces.", no_args_is_help=True)


@app.command("list")
def list_workspaces(
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON."),
):
    """List all workspaces."""
    try:
        with VoxyClient() as client:
            workspaces = client.get("/api/workspaces")
    except CliError as e:
        raise die(str(e))

    if as_json:
        print_json(workspaces)
        return

    default_ws = get_default_workspace()
    default_id = default_ws["id"] if default_ws else None
    table = Table(title=f"Workspaces ({len(workspaces)})")
    table.add_column("", width=1)  # active marker (voxy use)
    table.add_column("ID", style="dim", overflow="fold")
    table.add_column("Title", style="bold")
    table.add_column("Status")
    table.add_column("Fav")
    table.add_column("Age", justify="right")
    for ws in workspaces:
        table.add_row(
            "[green]›[/green]" if ws.get("id") == default_id else "",
            ws.get("id", ""),
            f"{ws.get('emoji') or ''} {ws.get('title', '')}".strip(),
            fmt_status(ws.get("status")),
            "*" if ws.get("is_favorite") else "",
            fmt_age(ws.get("created_at")),
        )
    console.print(table)


@app.command("create")
def create_workspace(
    title: str = typer.Argument(..., help="Workspace title."),
    description: str = typer.Option("", "--description", "-d", help="Description."),
):
    """Create a new workspace."""
    try:
        with VoxyClient() as client:
            ws = client.post(
                "/api/workspaces",
                json={"title": title, "description": description},
            )
    except CliError as e:
        raise die(str(e))
    console.print(f"[green]Created[/green] workspace [bold]{ws.get('title')}[/bold] ({ws.get('id')})")


@app.command("delete")
def delete_workspace(
    workspace: str = typer.Argument(..., help="Workspace name or id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
):
    """Delete a workspace (by name or id)."""
    try:
        with VoxyClient() as client:
            ws = get_workspace(client, workspace)
            if not yes:
                typer.confirm(
                    f"Delete workspace '{ws.get('title')}' ({ws.get('id')})?", abort=True
                )
            client.delete(f"/api/workspaces/{ws['id']}")
    except CliError as e:
        raise die(str(e))
    default_ws = get_default_workspace()
    if default_ws and default_ws["id"] == ws["id"]:
        from ..config import clear_default_workspace

        clear_default_workspace()
        console.print("[dim]cleared default workspace (it was deleted)[/dim]")
    console.print(f"[green]Deleted[/green] workspace [bold]{ws.get('title')}[/bold]")
