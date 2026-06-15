"""`voxy update` — pull the latest code and refresh the install.

Works on editable installs (the voxy package lives inside the git checkout).
Steps are diff-driven: Python deps reinstall, CLI reinstall and frontend
rebuild only run when the pulled commits touch them; --full forces everything.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import httpx
import typer

from ..client import CliError, die
from ..config import get_base_url
from ..output import console
from ..repo import find_repo_root, git, plan_update

BACKEND_SERVICE = "voxyflow-backend.service"


def _run_step(label: str, cmd: list[str], cwd: Path) -> None:
    console.print(f"[cyan]→[/cyan] {label} [dim]({' '.join(cmd)})[/dim]")
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip()[-2000:]
        raise CliError(f"{label} failed:\n{tail}")


def _wait_healthy(base_url: str, timeout: float = 45.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{base_url}/health", timeout=3.0)
            if resp.status_code == 200:
                return resp.json()
        except httpx.HTTPError:
            pass
        time.sleep(1.5)
    return None


def update(
    check: bool = typer.Option(False, "--check", help="Only report how far behind origin the install is."),
    no_restart: bool = typer.Option(False, "--no-restart", help="Skip the backend service restart."),
    full: bool = typer.Option(False, "--full", help="Force deps reinstall + frontend rebuild + restart."),
):
    """Update Voxyflow: git pull, refresh deps/build as needed, restart, verify."""
    repo = find_repo_root()
    if repo is None:
        raise die(
            "can't find the voxyflow git checkout behind this install — "
            "voxy update needs an editable install (see docs/SETUP.md; "
            "manual path: git pull && ./install.sh)"
        )

    try:
        branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        local = git(repo, "rev-parse", "--short", "HEAD")
        git(repo, "fetch", "--quiet", timeout=120.0)
        behind = int(git(repo, "rev-list", "--count", "HEAD..@{u}") or "0")
    except RuntimeError as e:
        raise die(str(e))

    if check:
        if behind:
            console.print(
                f"[yellow]{behind} commit(s) behind[/yellow] origin on [bold]{branch}[/bold] "
                f"(local {local}) — run [bold]voxy update[/bold]"
            )
        else:
            console.print(f"[green]up to date[/green] — {branch} @ {local}")
        return

    if behind == 0 and not full:
        console.print(f"[green]Already up to date[/green] — {branch} @ {local}")
        return

    try:
        if behind:
            console.print(f"[cyan]→[/cyan] pulling {behind} commit(s) on [bold]{branch}[/bold]")
            git(repo, "pull", "--ff-only", timeout=300.0)
        new = git(repo, "rev-parse", "--short", "HEAD")
        changed = git(repo, "diff", "--name-only", local, new).splitlines() if behind else []
    except RuntimeError as e:
        raise die(f"{e}\n(dirty or diverged checkout? resolve in {repo} and retry)")

    plan = plan_update(changed, full=full)
    pip = repo / "backend" / "venv" / "bin" / "pip"
    try:
        if plan["pip"]:
            if pip.exists():
                _run_step("python deps", [str(pip), "install", "--quiet", "-r", "backend/requirements.txt"], repo)
            else:
                console.print("[yellow]![/yellow] backend/venv missing — run ./install.sh")
        if plan["cli"] and pip.exists():
            _run_step("voxy CLI", [str(pip), "install", "--quiet", "-e", "./cli"], repo)
        if plan["frontend"]:
            fe = repo / "frontend-react"
            if not (fe / "node_modules").is_dir() or any(
                f == "frontend-react/package.json" for f in changed
            ):
                _run_step("frontend deps", ["npm", "install", "--silent"], fe)
            _run_step("frontend build", ["npm", "run", "build"], fe)
        if plan["backend_restart"] and not no_restart:
            _run_step("backend restart", ["systemctl", "--user", "restart", BACKEND_SERVICE], repo)
            console.print("[cyan]→[/cyan] waiting for the backend to come back…")
            health = _wait_healthy(get_base_url())
            if health is None:
                raise CliError(
                    "backend did not come back healthy within 45s — "
                    "check /tmp/voxyflow-backend.log (or run voxy doctor)"
                )
            console.print(
                f"[green]backend healthy[/green] — running [bold]{health.get('version', '?')}[/bold]"
            )
    except CliError as e:
        raise die(str(e))

    if behind:
        try:
            log = git(repo, "log", "--oneline", f"{local}..{new}")
            lines = log.splitlines()
            console.print(f"\n[bold]Updated[/bold] {local} → {new} ({len(lines)} commit(s)):")
            for line in lines[:15]:
                console.print(f"  [dim]{line}[/dim]")
            if len(lines) > 15:
                console.print(f"  [dim]… and {len(lines) - 15} more[/dim]")
        except RuntimeError:
            console.print(f"[bold]Updated[/bold] {local} → {new}")
    else:
        console.print("[green]Refresh complete[/green] (no new commits)")
