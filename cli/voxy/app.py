"""voxy — power CLI for Voxyflow.

Entry point: ``voxy`` console script (see pyproject.toml).
"""

from __future__ import annotations

import asyncio

import typer

from . import __version__
from .chatws import ChatError, ChatSession, ChatTimeout, chat_once
from .client import CliError, VoxyClient, die, get_workspace
from .commands import cards, config_cmd, doctor, jobs, skills, update, workers, workspaces
from .config import (
    clear_default_workspace,
    effective_workspace_ref,
    get_base_url,
    get_default_workspace,
    set_default_workspace,
)
from .output import console, print_json

app = typer.Typer(
    name="voxy",
    help="Power CLI for Voxyflow — chat, kanban, workers, jobs and skills.",
    no_args_is_help=True,
)
app.add_typer(workspaces.app, name="ws")
app.add_typer(cards.app, name="cards")
app.add_typer(workers.app, name="workers")
app.add_typer(jobs.app, name="jobs")
app.add_typer(skills.app, name="skills")
app.add_typer(config_cmd.app, name="config")
app.command("update")(update.update)
app.command("doctor")(doctor.doctor)


@app.callback()
def _root(
    version: bool = typer.Option(False, "--version", help="Show version and exit."),
):
    if version:
        console.print(f"voxy {__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# use — persistent default workspace
# ---------------------------------------------------------------------------

@app.command("use")
def use(
    workspace: str = typer.Argument(
        None, help="Workspace name or id to make the default. Omit to show the current one."
    ),
    clear: bool = typer.Option(False, "--clear", help="Clear the default workspace."),
):
    """Set the default workspace for all commands (override per-command with -w).

    `-w general` always forces the general chat regardless of the default.
    """
    if clear:
        clear_default_workspace()
        console.print("[green]Cleared[/green] default workspace — commands target the general chat again.")
        return

    if not workspace:
        current = get_default_workspace()
        if current:
            console.print(
                f"default workspace: [bold]{current.get('title', '?')}[/bold] [dim]({current['id']})[/dim]"
            )
        else:
            console.print("[dim]no default workspace set — `voxy use WORKSPACE` to set one[/dim]")
        return

    try:
        with VoxyClient() as client:
            ws = get_workspace(client, workspace)
    except CliError as e:
        raise die(str(e))
    set_default_workspace(ws["id"], ws.get("title", ""))
    console.print(
        f"[green]Switched to[/green] [bold]{ws.get('title')}[/bold] [dim]({ws['id']})[/dim] — "
        "override with -w, reset with `voxy use --clear`."
    )


# ---------------------------------------------------------------------------
# chat
# ---------------------------------------------------------------------------

def _resolve_workspace(workspace: str | None) -> tuple[str | None, str | None]:
    """Effective (workspace_id, title) for chat: -w wins, then `voxy use` default."""
    default_ws = get_default_workspace()
    ref = effective_workspace_ref(workspace, default_ws)
    if ref is None:
        return None, None
    if default_ws and ref == default_ws["id"] and not workspace:
        return default_ws["id"], default_ws.get("title")
    with VoxyClient() as client:
        ws = get_workspace(client, ref)
    return ws["id"], ws.get("title")


@app.command("chat")
def chat(
    message: str = typer.Argument(None, help="One-shot message. Omit for interactive REPL."),
    workspace: str = typer.Option(
        None, "--workspace", "-w",
        help="Workspace name or id ('general' forces the general chat; default: `voxy use` workspace, else general).",
    ),
    deep: bool = typer.Option(False, "--deep", help="Use the deep (slow, smart) model layer."),
    timeout: float = typer.Option(120.0, "--timeout", help="Seconds to wait for the full response."),
):
    """Chat with Voxy — one-shot if MESSAGE is given, interactive REPL otherwise."""
    base_url = get_base_url()
    try:
        workspace_id, workspace_title = _resolve_workspace(workspace)
    except CliError as e:
        raise die(str(e))

    if message:
        _chat_oneshot(base_url, message, workspace_id, deep, timeout)
    else:
        _chat_repl(base_url, workspace_id, deep, timeout, workspace_title)


def _chat_oneshot(base_url, message, workspace_id, deep, timeout):
    def on_token(token: str) -> None:
        print(token, end="", flush=True)

    try:
        asyncio.run(
            chat_once(base_url, message, workspace_id=workspace_id,
                      deep=deep, timeout=timeout, on_token=on_token)
        )
        print()
    except ChatTimeout:
        print()
        raise die(f"no response within {timeout:.0f}s — the model layer may be busy; try again or raise --timeout")
    except ChatError as e:
        raise die(f"chat failed: {e}")
    except (ConnectionError, OSError):
        raise die(f"cannot reach Voxyflow websocket at {base_url} — is the backend running?")


def _chat_repl(base_url, workspace_id, deep, timeout, workspace_title=None):
    console.print("[bold]voxy chat[/bold] — interactive. [dim]/quit to exit, /deep to toggle deep mode.[/dim]")
    if workspace_id:
        console.print(f"[dim]workspace: {workspace_title or workspace_id}[/dim]")
    ws_tag = f"[dim]{workspace_title}[/dim] " if workspace_title else ""

    async def repl():
        nonlocal deep
        try:
            session = ChatSession(base_url, workspace_id=workspace_id, timeout=timeout)
            await session.connect()
        except (ConnectionError, OSError, asyncio.TimeoutError):
            raise CliError(f"cannot reach Voxyflow websocket at {base_url} — is the backend running?")
        try:
            while True:
                try:
                    line = await asyncio.to_thread(
                        console.input,
                        f"{ws_tag}[bold cyan]you{' (deep)' if deep else ''} ›[/bold cyan] ",
                    )
                except (EOFError, KeyboardInterrupt):
                    break
                line = line.strip()
                if not line:
                    continue
                if line in ("/quit", "/exit", "/q"):
                    break
                if line == "/deep":
                    deep = not deep
                    console.print(f"[dim]deep mode: {'on' if deep else 'off'}[/dim]")
                    continue
                console.print("[bold magenta]voxy ›[/bold magenta] ", end="")
                try:
                    await session.send_and_stream(
                        line, deep=deep,
                        on_token=lambda t: print(t, end="", flush=True),
                    )
                    print()
                except ChatTimeout:
                    print()
                    console.print(f"[yellow]no response within {timeout:.0f}s — model layer may be busy[/yellow]")
                except ChatError as e:
                    print()
                    console.print(f"[red]chat error:[/red] {e}")
        finally:
            await session.close()

    try:
        asyncio.run(repl())
    except CliError as e:
        raise die(str(e))
    console.print("[dim]bye[/dim]")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@app.command("status")
def status(
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON."),
):
    """Backend health + counts overview (workspaces, workers, jobs)."""
    try:
        with VoxyClient() as client:
            health = client.get("/api/health")
            workspaces_list = client.get("/api/workspaces")
            tasks = client.get("/api/worker-tasks", params={"limit": 100}).get("tasks", [])
            jobs_data = client.get("/api/jobs")
    except CliError as e:
        raise die(str(e))

    jobs_list = jobs_data.get("jobs", []) if isinstance(jobs_data, dict) else jobs_data
    active = [t for t in tasks if t.get("status") in ("pending", "running")]

    if as_json:
        print_json({
            "base_url": get_base_url(),
            "health": health,
            "workspaces": len(workspaces_list),
            "workers_recent": len(tasks),
            "workers_active": len(active),
            "jobs": len(jobs_list),
            "jobs_enabled": sum(1 for j in jobs_list if j.get("enabled")),
        })
        return

    overall = health.get("status", "unknown")
    color = {"ok": "green", "healthy": "green", "degraded": "yellow"}.get(overall, "red")
    console.print(f"[bold]Voxyflow[/bold] @ {get_base_url()} — status: [{color}]{overall}[/{color}]")

    services = health.get("services", {})
    for name, svc in services.items():
        if name == "resources":
            continue
        s = svc.get("status", "?") if isinstance(svc, dict) else str(svc)
        scolor = "green" if s == "ok" else ("dim" if s == "not_applicable" else "yellow")
        console.print(f"  {name}: [{scolor}]{s}[/{scolor}]")
    resources = services.get("resources") or {}
    if resources:
        console.print(
            f"  resources: cpu {resources.get('cpu_pct', '?')}% · "
            f"ram {resources.get('ram_pct', '?')}% "
            f"({resources.get('ram_used_mb', 0):.0f}/{resources.get('ram_total_mb', 0):.0f} MB)"
        )

    console.print(
        f"\n  workspaces: [bold]{len(workspaces_list)}[/bold]"
        f"  ·  active workers: [bold]{len(active)}[/bold] (of {len(tasks)} recent)"
        f"  ·  jobs: [bold]{sum(1 for j in jobs_list if j.get('enabled'))}[/bold]/{len(jobs_list)} enabled"
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
