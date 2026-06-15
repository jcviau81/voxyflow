"""`voxy workers` — worker task monitoring and control."""

from __future__ import annotations

import time

import typer
from rich.live import Live
from rich.table import Table

from ..client import CliError, VoxyClient, die
from ..output import console, fmt_age, fmt_status, print_json

app = typer.Typer(
    help="Monitor and steer background workers.",
    invoke_without_command=True,
)


def _tasks_table(tasks: list[dict], title: str = "Worker tasks") -> Table:
    table = Table(title=f"{title} ({len(tasks)})")
    table.add_column("ID", style="dim", overflow="fold")
    table.add_column("Action", style="bold")
    table.add_column("Model")
    table.add_column("Status")
    table.add_column("Age", justify="right")
    table.add_column("Summary / Error", overflow="fold", max_width=60)
    for t in tasks:
        summary = t.get("error") or t.get("result_summary") or t.get("description") or ""
        table.add_row(
            t.get("id", ""),
            t.get("action", ""),
            t.get("model") or "",
            fmt_status(t.get("status")),
            fmt_age(t.get("created_at")),
            (summary or "")[:200],
        )
    return table


@app.callback()
def workers_main(ctx: typer.Context):
    """Monitor and steer background workers (default: list)."""
    if ctx.invoked_subcommand is None:
        list_workers()


@app.command("list")
def list_workers(
    status: str = typer.Option(None, "--status", help="Filter: pending/running/done/failed/cancelled."),
    limit: int = typer.Option(20, "--limit", "-n", help="Max tasks to show."),
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON."),
):
    """List recent worker tasks."""
    params = {"limit": limit}
    if status:
        params["status"] = status
    try:
        with VoxyClient() as client:
            data = client.get("/api/worker-tasks", params=params)
    except CliError as e:
        raise die(str(e))
    tasks = data.get("tasks", [])
    if as_json:
        print_json(tasks)
        return
    console.print(_tasks_table(tasks))


@app.command("peek")
def peek_worker(task_id: str = typer.Argument(..., help="Worker task id.")):
    """Live peek into a worker task (falls back to DB for finished tasks)."""
    try:
        with VoxyClient() as client:
            data = client.get(f"/api/worker-tasks/{task_id}/peek")
    except CliError as e:
        raise die(str(e))
    print_json(data)


@app.command("steer")
def steer_worker(
    task_id: str = typer.Argument(..., help="Worker task id."),
    message: str = typer.Argument(..., help="Steering message to inject."),
):
    """Inject a steering message into a running worker."""
    try:
        with VoxyClient() as client:
            data = client.post(f"/api/worker-tasks/{task_id}/steer", json={"message": message})
    except CliError as e:
        raise die(str(e))
    if data.get("queued"):
        console.print(f"[green]Steering message queued[/green] for {task_id}")
    else:
        console.print(f"[yellow]Not queued[/yellow] — task {task_id} may not be running")


@app.command("cancel")
def cancel_worker(task_id: str = typer.Argument(..., help="Worker task id.")):
    """Cancel a running worker task."""
    try:
        with VoxyClient() as client:
            data = client.post(f"/api/worker-tasks/{task_id}/cancel")
    except CliError as e:
        raise die(str(e))
    if data.get("cancelled"):
        console.print(f"[green]Cancelled[/green] {task_id}")
    else:
        console.print(f"[yellow]Nothing to cancel[/yellow] — task {task_id} not active")


@app.command("watch")
def watch_workers(
    interval: float = typer.Option(2.0, "--interval", "-i", help="Poll interval in seconds."),
    limit: int = typer.Option(20, "--limit", "-n", help="Max tasks to show."),
):
    """Live worker table — polls every 2s until Ctrl-C."""
    try:
        with VoxyClient() as client:
            with Live(console=console, refresh_per_second=4) as live:
                while True:
                    data = client.get("/api/worker-tasks", params={"limit": limit})
                    tasks = data.get("tasks", [])
                    live.update(_tasks_table(tasks, title="Worker tasks (watching, Ctrl-C to stop)"))
                    time.sleep(interval)
    except KeyboardInterrupt:
        pass
    except CliError as e:
        raise die(str(e))
