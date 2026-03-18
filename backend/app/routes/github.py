"""GitHub integration endpoints."""

import json
import os
import subprocess

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/github", tags=["github"])


@router.get("/validate/{owner}/{repo}")
async def validate_repo(owner: str, repo: str):
    """Validate a GitHub repo exists and return info."""
    try:
        result = subprocess.run(
            ["gh", "api", f"/repos/{owner}/{repo}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
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
        result = subprocess.run(
            ["gh", "repo", "clone", f"{owner}/{repo}", target_dir],
            capture_output=True,
            text=True,
            timeout=120,
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
