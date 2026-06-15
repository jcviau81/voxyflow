"""`voxy skills` — list and show installed skills.

Tries ``GET /api/skills`` first (a skills API may land later); falls back to
reading skill files directly from ``~/.voxyflow/skills/``:

- global skills: ``~/.voxyflow/skills/<skill>/SKILL.md``
- workspace skills: ``~/.voxyflow/skills/workspace-<uuid>/<skill>/SKILL.md``

``SKILL.md`` carries YAML frontmatter with ``name`` and ``description``.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.markdown import Markdown
from rich.table import Table

from ..client import CliError, VoxyClient, die
from ..output import console, print_json

SKILLS_DIR = Path.home() / ".voxyflow" / "skills"

app = typer.Typer(help="List and inspect Voxyflow skills.", no_args_is_help=True)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse simple ``key: value`` YAML frontmatter. Returns (meta, body)."""
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        lines = text.split("\n")
        for end, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                for raw in lines[1:end]:
                    if ":" in raw:
                        key, _, value = raw.partition(":")
                        meta[key.strip()] = value.strip().strip("'\"")
                body = "\n".join(lines[end + 1:])
                break
    return meta, body


def _scan_skill_dir(directory: Path, scope: str) -> list[dict]:
    skills = []
    if not directory.is_dir():
        return skills
    for entry in sorted(directory.iterdir()):
        skill_md = entry / "SKILL.md"
        if entry.is_dir() and skill_md.is_file():
            try:
                meta, body = parse_frontmatter(skill_md.read_text())
            except OSError:
                continue
            skills.append({
                "name": meta.get("name", entry.name),
                "description": meta.get("description", ""),
                "scope": scope,
                "path": str(skill_md),
                "body": body,
            })
    return skills


def load_skills_from_fs() -> list[dict]:
    """All skills from ~/.voxyflow/skills/ (global + per-workspace subdirs)."""
    skills = []
    if not SKILLS_DIR.is_dir():
        return skills
    skills.extend(
        s for s in _scan_skill_dir(SKILLS_DIR, "global")
        if not Path(s["path"]).parent.name.startswith("workspace-")
    )
    for entry in sorted(SKILLS_DIR.iterdir()):
        if entry.is_dir() and entry.name.startswith("workspace-"):
            ws_id = entry.name[len("workspace-"):]
            skills.extend(_scan_skill_dir(entry, f"workspace:{ws_id}"))
    return skills


def load_skills() -> list[dict]:
    """Try the API first; fall back to the filesystem."""
    try:
        with VoxyClient() as client:
            data = client.get("/api/skills")
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("skills"), list):
            return data["skills"]
    except CliError:
        pass
    return load_skills_from_fs()


@app.command("list")
def list_skills(
    as_json: bool = typer.Option(False, "--json", help="Output raw JSON."),
):
    """List installed skills (global and per-workspace)."""
    skills = load_skills()
    if as_json:
        print_json([{k: v for k, v in s.items() if k != "body"} for s in skills])
        return
    if not skills:
        console.print(f"[dim]No skills found (looked in {SKILLS_DIR} and /api/skills).[/dim]")
        return
    table = Table(title=f"Skills ({len(skills)})")
    table.add_column("Name", style="bold")
    table.add_column("Scope")
    table.add_column("Description", overflow="fold")
    for s in skills:
        table.add_row(s.get("name", ""), s.get("scope", ""), s.get("description", ""))
    console.print(table)


@app.command("show")
def show_skill(name: str = typer.Argument(..., help="Skill name.")):
    """Show a skill's full SKILL.md."""
    skills = load_skills()
    match = next(
        (s for s in skills if s.get("name", "").lower() == name.lower()), None
    )
    if match is None:
        raise die(f"skill {name!r} not found (try `voxy skills list`)")
    body = match.get("body")
    if body is None and match.get("path"):
        try:
            _, body = parse_frontmatter(Path(match["path"]).read_text())
        except OSError as e:
            raise die(f"cannot read {match['path']}: {e}")
    console.print(f"[bold]{match.get('name')}[/bold] [dim]({match.get('scope', '')})[/dim]")
    if match.get("description"):
        console.print(f"[italic]{match['description']}[/italic]\n")
    console.print(Markdown(body or ""))
