"""`voxy jobs` — scheduled job commands."""

from __future__ import annotations

import typer
from rich.table import Table

from ..client import CliError, VoxyClient, die
from ..output import console, fmt_status, print_json

app = typer.Typer(help="Manage scheduled jobs.", no_args_is_help=True)


@app.command("list")
def list_jobs(
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON."),
):
    """List scheduled jobs."""
    try:
        with VoxyClient() as client:
            data = client.get("/api/jobs")
    except CliError as e:
        raise die(str(e))
    jobs = data.get("jobs", data) if isinstance(data, dict) else data
    if as_json:
        print_json(jobs)
        return

    table = Table(title=f"Jobs ({len(jobs)})")
    table.add_column("ID", style="dim", overflow="fold")
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Schedule")
    table.add_column("Enabled")
    table.add_column("Last run", overflow="fold")
    table.add_column("Next run", overflow="fold")
    for j in jobs:
        table.add_row(
            j.get("id", ""),
            j.get("name", ""),
            j.get("type", ""),
            j.get("schedule", ""),
            "[green]yes[/green]" if j.get("enabled") else "[dim]no[/dim]",
            (j.get("last_run") or "-")[:19],
            (j.get("next_run") or "-")[:19],
        )
    console.print(table)


@app.command("run")
def run_job(job_id: str = typer.Argument(..., help="Job id (see `voxy jobs list`).")):
    """Trigger a job to run now."""
    try:
        with VoxyClient() as client:
            data = client.post(f"/api/jobs/{job_id}/run")
    except CliError as e:
        raise die(str(e))
    console.print(f"[green]Triggered[/green] job {job_id}")
    if isinstance(data, dict) and data:
        print_json(data)
