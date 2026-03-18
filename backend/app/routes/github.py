"""GitHub integration endpoints."""

import json
import os
import subprocess

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/github", tags=["github"])

SETTINGS_FILE = os.path.expanduser("~/.openclaw/workspace/voxyflow/settings.json")


def _load_pat() -> str | None:
    """Load GitHub PAT from settings file if configured."""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE) as f:
                settings = json.load(f)
                return settings.get("github", {}).get("token") or None
    except Exception:
        pass
    return None


def _run_gh(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess:
    """Run a gh CLI command, falling back to PAT auth if needed."""
    env = os.environ.copy()
    pat = _load_pat()
    if pat:
        env["GH_TOKEN"] = pat
    return subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


@router.get("/status")
async def github_status():
    """Check if GitHub is configured and accessible."""
    result = {
        "gh_installed": False,
        "gh_authenticated": False,
        "username": None,
        "token_configured": False,
        "method": None,
    }

    # Check gh CLI
    try:
        version = subprocess.run(
            ["gh", "--version"], capture_output=True, text=True, timeout=5
        )
        if version.returncode == 0:
            result["gh_installed"] = True

            # Check if authenticated (with PAT fallback via env)
            env = os.environ.copy()
            pat = _load_pat()
            if pat:
                env["GH_TOKEN"] = pat

            auth = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
            )
            if auth.returncode == 0:
                result["gh_authenticated"] = True
                result["method"] = "pat" if pat else "gh_cli"

                # Get username
                user = subprocess.run(
                    ["gh", "api", "/user", "--jq", ".login"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=env,
                )
                if user.returncode == 0:
                    result["username"] = user.stdout.strip()
    except FileNotFoundError:
        pass  # gh not installed
    except Exception:
        pass

    # Check for PAT in settings
    if _load_pat():
        result["token_configured"] = True
        if not result["gh_authenticated"]:
            result["method"] = "pat"

    return result


class TokenPayload(BaseModel):
    token: str


@router.post("/token")
async def save_github_token(payload: TokenPayload):
    """Save a GitHub PAT to settings."""
    token = payload.token.strip()
    if not token.startswith(("ghp_", "github_pat_")):
        raise HTTPException(400, "Token must start with ghp_ or github_pat_")

    # Load existing settings
    settings = {}
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE) as f:
                settings = json.load(f)
    except Exception:
        pass

    # Save token
    if "github" not in settings:
        settings["github"] = {}
    settings["github"]["token"] = token

    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

    return {"saved": True}


@router.delete("/token")
async def delete_github_token():
    """Remove saved GitHub PAT."""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE) as f:
                settings = json.load(f)
            if "github" in settings:
                settings["github"].pop("token", None)
                with open(SETTINGS_FILE, "w") as f:
                    json.dump(settings, f, indent=2)
    except Exception:
        pass
    return {"deleted": True}


@router.get("/validate/{owner}/{repo}")
async def validate_repo(owner: str, repo: str):
    """Validate a GitHub repo exists and return info."""
    # First check if GitHub is accessible at all
    try:
        result = _run_gh(["api", f"/repos/{owner}/{repo}"])
        if result.returncode != 0:
            stderr = result.stderr.lower()
            if "auth" in stderr or "login" in stderr or "token" in stderr:
                raise HTTPException(
                    401,
                    "GitHub not configured. Go to Settings → GitHub to connect.",
                )
            raise HTTPException(404, "Repository not found")

        data = json.loads(result.stdout)
        return {
            "valid": True,
            "full_name": data["full_name"],
            "description": data.get("description", ""),
            "default_branch": data["default_branch"],
            "language": data.get("language"),
            "stars": data.get("stargazers_count", 0),
            "private": data["private"],
            "html_url": data["html_url"],
            "clone_url": data["clone_url"],
            "updated_at": data["updated_at"],
        }
    except FileNotFoundError:
        raise HTTPException(
            503,
            "GitHub CLI (gh) not installed. Go to Settings → GitHub to configure.",
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "GitHub API timeout")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/clone")
async def clone_repo(owner: str, repo: str, target_dir: str | None = None):
    """Clone a repo locally."""
    if not target_dir:
        target_dir = os.path.expanduser(f"~/projects/{repo}")

    if os.path.exists(target_dir):
        return {"status": "already_exists", "path": target_dir}

    try:
        result = _run_gh(
            ["repo", "clone", f"{owner}/{repo}", target_dir], timeout=120
        )
        if result.returncode != 0:
            raise HTTPException(500, f"Clone failed: {result.stderr}")

        return {"status": "cloned", "path": target_dir}
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "Clone timeout")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
