"""Locate and reason about the git checkout behind an editable install.

Used by `voxy update` and `voxy doctor`. Pure helpers are unit-tested offline.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk up from the voxy package to the Voxyflow git checkout.

    Returns None for non-editable installs (e.g. plain pipx) where the
    package does not live inside the repo.
    """
    p = (start or Path(__file__)).resolve()
    for parent in [p, *p.parents]:
        if (
            (parent / ".git").exists()
            and (parent / "backend").is_dir()
            and (parent / "cli").is_dir()
        ):
            return parent
    return None


def plan_update(changed: list[str], full: bool = False) -> dict:
    """Decide which refresh steps a pulled diff requires (pure, testable).

    The CLI itself is an editable install, so code changes under cli/ apply
    immediately — only a packaging change needs a reinstall.
    """
    return {
        "pip": full or any(f.startswith("backend/requirements") for f in changed),
        "cli": full or "cli/pyproject.toml" in changed,
        "frontend": full or any(f.startswith("frontend-react/") for f in changed),
        "backend_restart": full
        or any(f.startswith(("backend/", "personality/")) for f in changed),
    }


def git(repo: Path, *args: str, timeout: float = 60.0) -> str:
    """Run a git command in the repo, returning stripped stdout.

    Raises RuntimeError with the captured output on failure.
    """
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()[:500]}"
        )
    return proc.stdout.strip()
