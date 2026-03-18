"""GitHub integration endpoints."""

import json
import os
import subprocess

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/github", tags=["github"])

SETTINGS_FILE = os.path.expanduser("~/.openclaw/workspace/voxyflow/settings.json")
GITHUB_API = "https://api.github.com"


def _load_pat() -> str | None:
    """Load GitHub PAT from keyring / settings.json / env — in that order."""
    # 1) Try keyring (optional dependency)
    try:
        import keyring
        token = keyring.get_password("voxyflow", "github_pat")
        if token:
            return token
    except Exception:
        pass

    # 2) settings.json github.pat OR github.token
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE) as f:
                settings = json.load(f)
            gh = settings.get("github", {})
            token = gh.get("pat") or gh.get("token")
            if token:
                return token
    except Exception:
        pass

    # 3) Environment variable
    return os.environ.get("GITHUB_TOKEN") or None


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    pat = _load_pat()
    if pat:
        headers["Authorization"] = f"Bearer {pat}"
    return headers


async def _gh_get(path: str) -> dict:
    """Perform a GET to the GitHub REST API. Raises HTTPException on errors."""
    url = f"{GITHUB_API}{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=_github_headers())
    except httpx.TimeoutException:
        raise HTTPException(504, "GitHub API timeout")
    except Exception as e:
        raise HTTPException(502, f"GitHub API unreachable: {e}")

    if resp.status_code == 401:
        raise HTTPException(401, "GitHub token invalid or expired")
    if resp.status_code == 403:
        raise HTTPException(403, "GitHub rate limit exceeded or access forbidden")
    if resp.status_code == 404:
        raise HTTPException(404, "Repository not found")
    if not resp.is_success:
        raise HTTPException(resp.status_code, f"GitHub API error: {resp.text[:200]}")

    return resp.json()


# ---------------------------------------------------------------------------
# New REST endpoints
# ---------------------------------------------------------------------------

@router.get("/repo/{owner}/{repo}")
async def repo_info(owner: str, repo: str):
    """Return basic repo metadata."""
    data = await _gh_get(f"/repos/{owner}/{repo}")
    return {
        "name": data["name"],
        "full_name": data["full_name"],
        "description": data.get("description") or "",
        "html_url": data["html_url"],
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "language": data.get("language"),
        "open_issues_count": data.get("open_issues_count", 0),
        "default_branch": data.get("default_branch", "main"),
        "private": data.get("private", False),
        "pushed_at": data.get("pushed_at"),
        "updated_at": data.get("updated_at"),
    }


@router.get("/repo/{owner}/{repo}/issues")
async def repo_issues(owner: str, repo: str):
    """Return up to 20 open issues (excludes PRs)."""
    data = await _gh_get(f"/repos/{owner}/{repo}/issues?state=open&per_page=20&pulls=false")
    # GitHub /issues also returns PRs — filter them out
    issues = [item for item in data if "pull_request" not in item]
    return [
        {
            "number": issue["number"],
            "title": issue["title"],
            "html_url": issue["html_url"],
            "labels": [lb["name"] for lb in issue.get("labels", [])],
            "assignee": issue["assignee"]["login"] if issue.get("assignee") else None,
            "created_at": issue.get("created_at"),
        }
        for issue in issues[:20]
    ]


@router.get("/repo/{owner}/{repo}/pulls")
async def repo_pulls(owner: str, repo: str):
    """Return up to 20 open pull requests."""
    data = await _gh_get(f"/repos/{owner}/{repo}/pulls?state=open&per_page=20")
    return [
        {
            "number": pr["number"],
            "title": pr["title"],
            "html_url": pr["html_url"],
            "draft": pr.get("draft", False),
            "created_at": pr.get("created_at"),
            "user": pr["user"]["login"] if pr.get("user") else None,
        }
        for pr in data[:20]
    ]


@router.get("/repo/{owner}/{repo}/status")
async def repo_status(owner: str, repo: str):
    """Quick health check: repo exists, last commit info, latest CI run status."""
    # Repo info
    repo_data = await _gh_get(f"/repos/{owner}/{repo}")

    # Latest commit on default branch
    branch = repo_data.get("default_branch", "main")
    last_commit: dict | None = None
    try:
        commits = await _gh_get(f"/repos/{owner}/{repo}/commits?per_page=1")
        if commits:
            c = commits[0]
            last_commit = {
                "sha": c["sha"][:7],
                "message": (c.get("commit", {}).get("message") or "")[:100],
                "author": c.get("commit", {}).get("author", {}).get("name"),
                "date": c.get("commit", {}).get("author", {}).get("date"),
                "html_url": c.get("html_url"),
            }
    except HTTPException:
        pass

    # Latest CI run status (GitHub Actions)
    ci_status: str | None = None
    ci_url: str | None = None
    try:
        runs = await _gh_get(f"/repos/{owner}/{repo}/actions/runs?per_page=1&branch={branch}")
        run_list = runs.get("workflow_runs", [])
        if run_list:
            run = run_list[0]
            conclusion = run.get("conclusion")  # success | failure | cancelled | None
            status = run.get("status")          # queued | in_progress | completed
            ci_status = conclusion if conclusion else status
            ci_url = run.get("html_url")
    except HTTPException:
        pass  # Actions not configured or private repo — that's fine

    return {
        "exists": True,
        "full_name": repo_data["full_name"],
        "private": repo_data.get("private", False),
        "default_branch": branch,
        "last_commit": last_commit,
        "ci_status": ci_status,
        "ci_url": ci_url,
        "open_issues": repo_data.get("open_issues_count", 0),
        "stars": repo_data.get("stargazers_count", 0),
    }


# ---------------------------------------------------------------------------
# Existing endpoints (kept intact)
# ---------------------------------------------------------------------------

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
        pass
    except Exception:
        pass

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

    settings = {}
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE) as f:
                settings = json.load(f)
    except Exception:
        pass

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
                settings["github"].pop("pat", None)
                with open(SETTINGS_FILE, "w") as f:
                    json.dump(settings, f, indent=2)
    except Exception:
        pass
    return {"deleted": True}


@router.get("/validate/{owner}/{repo}")
async def validate_repo(owner: str, repo: str):
    """Validate a GitHub repo exists and return info."""
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
