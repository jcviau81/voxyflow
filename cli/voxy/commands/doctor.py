"""`voxy doctor` — diagnose (and optionally fix) a Voxyflow install.

Read-only by default; --fix restarts inactive services and re-bootstraps a
rejected auth token, then re-runs the checks once.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx
import typer

from ..chatws import ChatSession
from ..client import CliError, VoxyClient
from ..config import TOKEN_PATH, get_base_url, load_token
from ..output import console
from ..repo import find_repo_root, git

SERVICES = ("voxyflow-backend.service", "voxyflow-frontend.service")
MIN_FREE_GB = 2.0


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail | skip
    detail: str
    fix: str | None = None  # what --fix will do / what the user should do


def _systemctl_available() -> bool:
    return shutil.which("systemctl") is not None


def _unit_state(unit: str) -> str:
    proc = subprocess.run(
        ["systemctl", "--user", "is-active", unit],
        capture_output=True, text=True, timeout=10,
    )
    return proc.stdout.strip() or "unknown"


def run_checks(base_url: str) -> list[Check]:
    checks: list[Check] = []

    # 1. Backend HTTP + version
    health: dict = {}
    try:
        resp = httpx.get(f"{base_url}/health", timeout=5.0)
        health = resp.json()
        bad = [k for k, v in health.get("checks", {}).items() if v != "ok"]
        if resp.status_code == 200:
            checks.append(Check(
                "backend", "ok",
                f"{base_url} — {health.get('version', '?')} up {health.get('uptime_seconds', 0)}s",
            ))
        else:
            checks.append(Check(
                "backend", "fail",
                f"degraded — failing: {', '.join(bad) or '?'}",
                fix="check /tmp/voxyflow-backend.log",
            ))
    except (httpx.HTTPError, ValueError) as e:
        checks.append(Check(
            "backend", "fail", f"unreachable at {base_url} ({type(e).__name__})",
            fix="restart voxyflow-backend.service",
        ))

    backend_up = checks[0].status == "ok"

    # 2. Per-service detail from /api/health
    if backend_up:
        try:
            svc = httpx.get(f"{base_url}/api/health", timeout=5.0).json().get("services", {})
            bad = [
                f"{name}={s.get('status')}"
                for name, s in svc.items()
                if isinstance(s, dict) and s.get("status") not in ("ok", "not_applicable", None)
            ]
            if bad:
                checks.append(Check("services", "warn", ", ".join(bad)))
            else:
                checks.append(Check("services", "ok", f"{len(svc)} services reporting"))
        except (httpx.HTTPError, ValueError) as e:
            checks.append(Check("services", "warn", f"/api/health unreadable ({type(e).__name__})"))
    else:
        checks.append(Check("services", "skip", "backend down"))

    # 3. Auth token
    if backend_up:
        try:
            with VoxyClient(base_url) as client:
                client.get("/api/workspaces")
            checks.append(Check("auth", "ok", f"token accepted ({TOKEN_PATH})"))
        except CliError as e:
            fixable = "401" in str(e) or "403" in str(e)
            checks.append(Check(
                "auth", "fail", str(e)[:120],
                fix="re-bootstrap the token" if fixable else None,
            ))
    else:
        checks.append(Check("auth", "skip", "backend down"))

    # 4. Websocket
    if backend_up:
        async def _ws_probe() -> None:
            session = ChatSession(base_url, timeout=10.0)
            try:
                await session.connect()
            finally:
                await session.close()

        try:
            asyncio.run(asyncio.wait_for(_ws_probe(), timeout=15.0))
            checks.append(Check("websocket", "ok", "/ws connect + session sync"))
        except Exception as e:  # noqa: BLE001 — any failure mode is the same finding
            checks.append(Check(
                "websocket", "fail", f"cannot connect to /ws ({type(e).__name__})",
                fix="check the reverse proxy /ws route (Caddyfile)",
            ))
    else:
        checks.append(Check("websocket", "skip", "backend down"))

    # 5. systemd units
    if _systemctl_available():
        for unit in SERVICES:
            try:
                state = _unit_state(unit)
            except (OSError, subprocess.TimeoutExpired):
                checks.append(Check(unit, "warn", "systemctl query failed"))
                continue
            if state == "active":
                checks.append(Check(unit, "ok", "active"))
            else:
                checks.append(Check(unit, "fail", state, fix=f"systemctl --user restart {unit}"))
    else:
        checks.append(Check("systemd", "skip", "systemctl not available"))

    # 6. Stale code: running backend commit vs local checkout
    repo = find_repo_root()
    if backend_up and repo is not None:
        try:
            local = git(repo, "rev-parse", "--short", "HEAD")
            running = str(health.get("version", ""))
            if running and running != "dev":
                if local.startswith(running) or running.startswith(local):
                    checks.append(Check("code", "ok", f"backend runs current checkout ({local})"))
                else:
                    checks.append(Check(
                        "code", "warn",
                        f"backend runs {running}, checkout is at {local}",
                        fix="restart the backend (or run voxy update)",
                    ))
            else:
                checks.append(Check("code", "skip", "backend reports no git version"))
        except RuntimeError as e:
            checks.append(Check("code", "warn", str(e)[:120]))
    else:
        checks.append(Check("code", "skip", "backend down" if repo else "no git checkout found"))

    # 7. Frontend build
    if repo is not None:
        dist = repo / "frontend-react" / "dist" / "index.html"
        if dist.exists():
            checks.append(Check("frontend build", "ok", "dist/index.html present"))
        else:
            checks.append(Check(
                "frontend build", "fail", "frontend-react/dist missing",
                fix="cd frontend-react && npm run build (or ./install.sh)",
            ))

    # 8. Memory store
    chroma = Path.home() / ".voxyflow" / "chroma"
    if chroma.is_dir():
        checks.append(Check("memory store", "ok", str(chroma)))
    else:
        checks.append(Check(
            "memory store", "warn",
            f"{chroma} missing (created on first memory write)",
        ))

    # 9. Disk space
    usage = shutil.disk_usage(Path.home())
    free_gb = usage.free / 1e9
    if free_gb < MIN_FREE_GB:
        checks.append(Check(
            "disk", "warn", f"only {free_gb:.1f} GB free on home",
            fix="free up disk space",
        ))
    else:
        checks.append(Check("disk", "ok", f"{free_gb:.0f} GB free"))

    # 10. claude CLI (needed by the default CLI provider)
    if shutil.which("claude"):
        checks.append(Check("claude CLI", "ok", shutil.which("claude") or ""))
    else:
        checks.append(Check(
            "claude CLI", "warn",
            "not on PATH — the cli provider type can't spawn workers",
        ))

    return checks


def _apply_fixes(checks: list[Check], base_url: str) -> list[str]:
    """Apply automatic fixes for failed checks; return what was done."""
    actions: list[str] = []
    for check in checks:
        if check.status != "fail":
            continue
        if check.name in SERVICES and _systemctl_available():
            subprocess.run(
                ["systemctl", "--user", "restart", check.name],
                capture_output=True, timeout=30,
            )
            actions.append(f"restarted {check.name}")
        elif check.name == "auth" and check.fix == "re-bootstrap the token":
            try:
                TOKEN_PATH.unlink(missing_ok=True)
                load_token(base_url)
                actions.append("re-bootstrapped auth token")
            except Exception as e:  # noqa: BLE001
                actions.append(f"token re-bootstrap failed: {e}")
    return actions


STATUS_STYLE = {"ok": "green", "warn": "yellow", "fail": "red", "skip": "dim"}


def _print_report(checks: list[Check]) -> None:
    from rich.table import Table

    table = Table(title="voxy doctor")
    table.add_column("check", style="bold")
    table.add_column("status")
    table.add_column("detail", overflow="fold")
    table.add_column("fix", style="dim", overflow="fold")
    for c in checks:
        style = STATUS_STYLE[c.status]
        table.add_row(c.name, f"[{style}]{c.status}[/{style}]", c.detail, c.fix or "")
    console.print(table)


def doctor(
    fix: bool = typer.Option(False, "--fix", help="Restart failed services / re-bootstrap a bad token, then re-check."),
):
    """Diagnose the Voxyflow install: backend, services, auth, websocket, build, disk."""
    base_url = get_base_url()
    checks = run_checks(base_url)
    _print_report(checks)

    failed = [c for c in checks if c.status == "fail"]
    if fix and failed:
        actions = _apply_fixes(checks, base_url)
        if actions:
            console.print("\n[bold]fixes applied:[/bold] " + "; ".join(actions))
            import time

            time.sleep(3.0)  # give restarted services a moment
            checks = run_checks(base_url)
            _print_report(checks)
            failed = [c for c in checks if c.status == "fail"]
        else:
            console.print("[dim]no automatic fix available for the failures above[/dim]")

    warns = [c for c in checks if c.status == "warn"]
    if not failed and not warns:
        console.print("[green]all checks passed[/green]")
    elif not failed:
        console.print(f"[yellow]{len(warns)} warning(s)[/yellow] — nothing fatal")
    else:
        console.print(f"[red]{len(failed)} check(s) failing[/red]" + ("" if fix else " — try voxy doctor --fix"))
        raise typer.Exit(code=1)
