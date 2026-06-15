"""`voxy cards` — kanban card commands."""

from __future__ import annotations

import typer
from rich.table import Table

from ..client import CliError, VoxyClient, die, get_workspace
from ..config import effective_workspace_ref, get_default_workspace
from ..output import console, fmt_age, fmt_status, print_json

app = typer.Typer(help="Manage kanban cards.", no_args_is_help=True)

WS_HELP = "Workspace name or id (default: the `voxy use` workspace)."


def _require_workspace_ref(workspace: str | None) -> str:
    """Explicit -w, else the `voxy use` default — error when neither is set."""
    ref = effective_workspace_ref(workspace, get_default_workspace())
    if not ref:
        raise CliError(
            "no workspace given — pass -w WORKSPACE or set a default with `voxy use WORKSPACE`"
        )
    return ref


@app.command("list")
def list_cards(
    workspace: str = typer.Option(None, "--workspace", "-w", help=WS_HELP),
    status: str = typer.Option(None, "--status", help="Filter by status (backlog/todo/in-progress/done)."),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON."),
):
    """List cards in a workspace."""
    try:
        with VoxyClient() as client:
            ws = get_workspace(client, _require_workspace_ref(workspace))
            cards = client.get(f"/api/workspaces/{ws['id']}/cards")
    except CliError as e:
        raise die(str(e))

    if status:
        cards = [c for c in cards if c.get("status") == status]

    if as_json:
        print_json(cards)
        return

    table = Table(title=f"Cards in {ws.get('title')} ({len(cards)})")
    table.add_column("ID", style="dim", overflow="fold")
    table.add_column("Title", style="bold", overflow="fold")
    table.add_column("Status")
    table.add_column("Pri", justify="right")
    table.add_column("Agent")
    table.add_column("Age", justify="right")
    for c in cards:
        table.add_row(
            c.get("id", ""),
            c.get("title", ""),
            fmt_status(c.get("status")),
            str(c.get("priority", "")),
            c.get("agent_assigned") or "",
            fmt_age(c.get("created_at")),
        )
    console.print(table)


@app.command("add")
def add_card(
    title: str = typer.Argument(..., help="Card title."),
    workspace: str = typer.Option(None, "--workspace", "-w", help=WS_HELP),
    description: str = typer.Option("", "--description", "-d", help="Card description."),
):
    """Create a card in a workspace."""
    try:
        with VoxyClient() as client:
            ws = get_workspace(client, _require_workspace_ref(workspace))
            card = client.post(
                f"/api/workspaces/{ws['id']}/cards",
                json={"title": title, "description": description},
            )
    except CliError as e:
        raise die(str(e))
    console.print(
        f"[green]Created[/green] card [bold]{card.get('title')}[/bold] "
        f"({card.get('id')}) status={card.get('status')}"
    )


@app.command("move")
def move_card(
    card_id: str = typer.Argument(..., help="Card id."),
    status: str = typer.Argument(..., help="New status (backlog/todo/in-progress/done)."),
):
    """Move a card to another status column."""
    try:
        with VoxyClient() as client:
            card = client.patch(f"/api/cards/{card_id}", json={"status": status})
    except CliError as e:
        raise die(str(e))
    console.print(f"[green]Moved[/green] [bold]{card.get('title')}[/bold] → {card.get('status')}")


@app.command("done")
def done_card(card_id: str = typer.Argument(..., help="Card id.")):
    """Mark a card as done."""
    try:
        with VoxyClient() as client:
            card = client.patch(f"/api/cards/{card_id}", json={"status": "done"})
    except CliError as e:
        raise die(str(e))
    console.print(f"[green]Done[/green] [bold]{card.get('title')}[/bold]")


@app.command("rm")
def remove_card(
    card_id: str = typer.Argument(..., help="Card id."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
):
    """Delete a card (archives it first — the API requires archive-then-delete)."""
    try:
        with VoxyClient() as client:
            if not yes:
                typer.confirm(f"Delete card {card_id}?", abort=True)
            try:
                client.post(f"/api/cards/{card_id}/archive")
            except CliError:
                pass  # already archived (or archive unsupported) — try delete anyway
            client.delete(f"/api/cards/{card_id}")
    except CliError as e:
        raise die(str(e))
    console.print(f"[green]Deleted[/green] card {card_id}")
