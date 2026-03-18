"""GitHub tools — let AI agents interact with GitHub repos."""

import json
import os
import subprocess
from typing import Any, Dict

from app.tools.registry import ToolDefinition, ToolResult, register_tool

SETTINGS_FILE = os.path.expanduser("~/.openclaw/workspace/voxyflow/settings.json")


def _gh_env() -> dict:
    """Return env dict with GH_TOKEN if a PAT is configured."""
    env = os.environ.copy()
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE) as f:
                token = json.load(f).get("github", {}).get("token")
                if token:
                    env["GH_TOKEN"] = token
    except Exception:
        pass
    return env


def _run_gh(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh"] + args, capture_output=True, text=True, timeout=timeout, env=_gh_env()
    )


# ---------------------------------------------------------------------------
# github_status — check GitHub connection
# ---------------------------------------------------------------------------

async def _github_status(params: Dict[str, Any], db=None) -> ToolResult:
    try:
        r = _run_gh(["auth", "status"])
        if r.returncode == 0:
            user = _run_gh(["api", "/user", "--jq", ".login"])
            username = user.stdout.strip() if user.returncode == 0 else "unknown"
            return ToolResult(success=True, data={"authenticated": True, "username": username})
        return ToolResult(success=True, data={"authenticated": False, "message": r.stderr.strip()})
    except FileNotFoundError:
        return ToolResult(success=False, error="gh CLI not installed")
    except Exception as e:
        return ToolResult(success=False, error=str(e))

register_tool(
    ToolDefinition(
        name="github_status",
        description="Check if GitHub is connected and authenticated. Returns username.",
        parameters={"type": "object", "properties": {}, "required": []},
    ),
    _github_status,
)


# ---------------------------------------------------------------------------
# github_validate — check if a repo exists
# ---------------------------------------------------------------------------

async def _github_validate(params: Dict[str, Any], db=None) -> ToolResult:
    repo = params.get("repo", "")
    if "/" not in repo:
        return ToolResult(success=False, error="Repo must be owner/repo format")
    try:
        r = _run_gh(["api", f"/repos/{repo}", "--jq", ".full_name,.description,.default_branch,.language,.stargazers_count,.private,.html_url"])
        if r.returncode != 0:
            return ToolResult(success=False, error=f"Repo not found: {repo}")
        lines = r.stdout.strip().split("\n")
        return ToolResult(success=True, data={
            "full_name": lines[0] if len(lines) > 0 else repo,
            "description": lines[1] if len(lines) > 1 else "",
            "default_branch": lines[2] if len(lines) > 2 else "main",
            "language": lines[3] if len(lines) > 3 else None,
            "stars": int(lines[4]) if len(lines) > 4 and lines[4].isdigit() else 0,
            "private": lines[5] == "true" if len(lines) > 5 else False,
            "html_url": lines[6] if len(lines) > 6 else "",
        })
    except Exception as e:
        return ToolResult(success=False, error=str(e))

register_tool(
    ToolDefinition(
        name="github_validate",
        description="Check if a GitHub repository exists and return its info.",
        parameters={
            "type": "object",
            "properties": {"repo": {"type": "string", "description": "owner/repo"}},
            "required": ["repo"],
        },
    ),
    _github_validate,
)


# ---------------------------------------------------------------------------
# github_clone — clone a repo locally
# ---------------------------------------------------------------------------

async def _github_clone(params: Dict[str, Any], db=None) -> ToolResult:
    repo = params.get("repo", "")
    target = params.get("target_dir", "")
    if not repo:
        return ToolResult(success=False, error="repo is required")
    if not target:
        name = repo.split("/")[-1] if "/" in repo else repo
        target = os.path.expanduser(f"~/projects/{name}")
    if os.path.exists(target):
        return ToolResult(success=True, data={"status": "already_exists", "path": target})
    try:
        r = _run_gh(["repo", "clone", repo, target], timeout=120)
        if r.returncode != 0:
            return ToolResult(success=False, error=r.stderr.strip())
        return ToolResult(success=True, data={"status": "cloned", "path": target})
    except Exception as e:
        return ToolResult(success=False, error=str(e))

register_tool(
    ToolDefinition(
        name="github_clone",
        description="Clone a GitHub repository locally.",
        parameters={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/repo"},
                "target_dir": {"type": "string", "description": "Local path to clone to (optional)"},
            },
            "required": ["repo"],
        },
    ),
    _github_clone,
)


# ---------------------------------------------------------------------------
# github_create — create a new repo
# ---------------------------------------------------------------------------

async def _github_create(params: Dict[str, Any], db=None) -> ToolResult:
    name = params.get("name", "")
    if not name:
        return ToolResult(success=False, error="name is required")
    args = ["repo", "create", name]
    if params.get("private", True):
        args.append("--private")
    else:
        args.append("--public")
    if params.get("description"):
        args.extend(["--description", params["description"]])
    try:
        r = _run_gh(args)
        if r.returncode != 0:
            return ToolResult(success=False, error=r.stderr.strip())
        return ToolResult(success=True, data={"created": True, "url": r.stdout.strip()})
    except Exception as e:
        return ToolResult(success=False, error=str(e))

register_tool(
    ToolDefinition(
        name="github_create",
        description="Create a new GitHub repository.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Repo name (or owner/name)"},
                "private": {"type": "boolean", "description": "Private repo (default true)"},
                "description": {"type": "string", "description": "Repo description"},
            },
            "required": ["name"],
        },
    ),
    _github_create,
)


# ---------------------------------------------------------------------------
# github_issues — list issues
# ---------------------------------------------------------------------------

async def _github_issues(params: Dict[str, Any], db=None) -> ToolResult:
    repo = params.get("repo", "")
    if not repo:
        return ToolResult(success=False, error="repo is required")
    args = ["issue", "list", "-R", repo, "--json", "number,title,state,labels,assignees,createdAt"]
    limit = params.get("limit", 20)
    args.extend(["--limit", str(limit)])
    if params.get("state"):
        args.extend(["--state", params["state"]])
    try:
        r = _run_gh(args)
        if r.returncode != 0:
            return ToolResult(success=False, error=r.stderr.strip())
        issues = json.loads(r.stdout)
        return ToolResult(success=True, data={"count": len(issues), "issues": issues})
    except Exception as e:
        return ToolResult(success=False, error=str(e))

register_tool(
    ToolDefinition(
        name="github_issues",
        description="List issues for a GitHub repository.",
        parameters={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/repo"},
                "state": {"type": "string", "description": "open, closed, or all"},
                "limit": {"type": "integer", "description": "Max issues to return (default 20)"},
            },
            "required": ["repo"],
        },
    ),
    _github_issues,
)


# ---------------------------------------------------------------------------
# github_create_issue — create an issue
# ---------------------------------------------------------------------------

async def _github_create_issue(params: Dict[str, Any], db=None) -> ToolResult:
    repo = params.get("repo", "")
    title = params.get("title", "")
    if not repo or not title:
        return ToolResult(success=False, error="repo and title are required")
    args = ["issue", "create", "-R", repo, "--title", title]
    if params.get("body"):
        args.extend(["--body", params["body"]])
    if params.get("labels"):
        args.extend(["--label", ",".join(params["labels"])])
    try:
        r = _run_gh(args)
        if r.returncode != 0:
            return ToolResult(success=False, error=r.stderr.strip())
        return ToolResult(success=True, data={"created": True, "url": r.stdout.strip()})
    except Exception as e:
        return ToolResult(success=False, error=str(e))

register_tool(
    ToolDefinition(
        name="github_create_issue",
        description="Create a new issue in a GitHub repository.",
        parameters={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/repo"},
                "title": {"type": "string", "description": "Issue title"},
                "body": {"type": "string", "description": "Issue body (markdown)"},
                "labels": {"type": "array", "items": {"type": "string"}, "description": "Labels"},
            },
            "required": ["repo", "title"],
        },
    ),
    _github_create_issue,
)


# ---------------------------------------------------------------------------
# github_pr_list — list PRs
# ---------------------------------------------------------------------------

async def _github_pr_list(params: Dict[str, Any], db=None) -> ToolResult:
    repo = params.get("repo", "")
    if not repo:
        return ToolResult(success=False, error="repo is required")
    args = ["pr", "list", "-R", repo, "--json", "number,title,state,headRefName,author,createdAt"]
    if params.get("state"):
        args.extend(["--state", params["state"]])
    args.extend(["--limit", str(params.get("limit", 20))])
    try:
        r = _run_gh(args)
        if r.returncode != 0:
            return ToolResult(success=False, error=r.stderr.strip())
        prs = json.loads(r.stdout)
        return ToolResult(success=True, data={"count": len(prs), "prs": prs})
    except Exception as e:
        return ToolResult(success=False, error=str(e))

register_tool(
    ToolDefinition(
        name="github_pr_list",
        description="List pull requests for a GitHub repository.",
        parameters={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/repo"},
                "state": {"type": "string", "description": "open, closed, merged, or all"},
                "limit": {"type": "integer", "description": "Max PRs to return (default 20)"},
            },
            "required": ["repo"],
        },
    ),
    _github_pr_list,
)


# ---------------------------------------------------------------------------
# github_pr_create — create a PR
# ---------------------------------------------------------------------------

async def _github_pr_create(params: Dict[str, Any], db=None) -> ToolResult:
    repo = params.get("repo", "")
    title = params.get("title", "")
    if not repo or not title:
        return ToolResult(success=False, error="repo and title are required")
    args = ["pr", "create", "-R", repo, "--title", title]
    if params.get("body"):
        args.extend(["--body", params["body"]])
    if params.get("base"):
        args.extend(["--base", params["base"]])
    if params.get("head"):
        args.extend(["--head", params["head"]])
    try:
        r = _run_gh(args)
        if r.returncode != 0:
            return ToolResult(success=False, error=r.stderr.strip())
        return ToolResult(success=True, data={"created": True, "url": r.stdout.strip()})
    except Exception as e:
        return ToolResult(success=False, error=str(e))

register_tool(
    ToolDefinition(
        name="github_pr_create",
        description="Create a pull request.",
        parameters={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/repo"},
                "title": {"type": "string", "description": "PR title"},
                "body": {"type": "string", "description": "PR body (markdown)"},
                "base": {"type": "string", "description": "Base branch (default: repo default)"},
                "head": {"type": "string", "description": "Head branch"},
            },
            "required": ["repo", "title"],
        },
    ),
    _github_pr_create,
)


# ---------------------------------------------------------------------------
# github_git_status — local git status
# ---------------------------------------------------------------------------

async def _github_git_status(params: Dict[str, Any], db=None) -> ToolResult:
    path = params.get("path", ".")
    path = os.path.expanduser(path)
    if not os.path.isdir(path):
        return ToolResult(success=False, error=f"Directory not found: {path}")
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True,
            timeout=10, cwd=path,
        )
        branch = subprocess.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True,
            timeout=5, cwd=path,
        )
        if r.returncode != 0:
            return ToolResult(success=False, error="Not a git repository")
        files = [line.strip() for line in r.stdout.strip().split("\n") if line.strip()]
        return ToolResult(success=True, data={
            "branch": branch.stdout.strip() if branch.returncode == 0 else "unknown",
            "clean": len(files) == 0,
            "changed_files": files[:50],
            "total_changes": len(files),
        })
    except Exception as e:
        return ToolResult(success=False, error=str(e))

register_tool(
    ToolDefinition(
        name="github_git_status",
        description="Check git status of a local repository.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the repo (default: .)"},
            },
            "required": [],
        },
    ),
    _github_git_status,
)


# ---------------------------------------------------------------------------
# github_commit — stage + commit
# ---------------------------------------------------------------------------

async def _github_commit(params: Dict[str, Any], db=None) -> ToolResult:
    path = os.path.expanduser(params.get("path", "."))
    message = params.get("message", "")
    if not message:
        return ToolResult(success=False, error="Commit message is required")
    try:
        # Stage
        files = params.get("files")
        if files:
            subprocess.run(["git", "add"] + files, cwd=path, capture_output=True, timeout=10)
        else:
            subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True, timeout=10)
        # Commit
        r = subprocess.run(
            ["git", "commit", "-m", message], capture_output=True, text=True,
            timeout=15, cwd=path,
        )
        if r.returncode != 0:
            return ToolResult(success=False, error=r.stderr.strip() or r.stdout.strip())
        return ToolResult(success=True, data={"committed": True, "output": r.stdout.strip()})
    except Exception as e:
        return ToolResult(success=False, error=str(e))

register_tool(
    ToolDefinition(
        name="github_commit",
        description="Stage and commit changes in a local git repo.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo path (default: .)"},
                "message": {"type": "string", "description": "Commit message"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Files to stage (default: all)"},
            },
            "required": ["message"],
        },
    ),
    _github_commit,
)


# ---------------------------------------------------------------------------
# github_push — push to remote
# ---------------------------------------------------------------------------

async def _github_push(params: Dict[str, Any], db=None) -> ToolResult:
    path = os.path.expanduser(params.get("path", "."))
    try:
        args = ["git", "push"]
        if params.get("set_upstream"):
            branch = subprocess.run(
                ["git", "branch", "--show-current"], capture_output=True, text=True,
                timeout=5, cwd=path,
            )
            if branch.returncode == 0:
                args.extend(["-u", "origin", branch.stdout.strip()])
        r = subprocess.run(args, capture_output=True, text=True, timeout=60, cwd=path)
        if r.returncode != 0:
            return ToolResult(success=False, error=r.stderr.strip())
        return ToolResult(success=True, data={"pushed": True, "output": r.stderr.strip() or r.stdout.strip()})
    except Exception as e:
        return ToolResult(success=False, error=str(e))

register_tool(
    ToolDefinition(
        name="github_push",
        description="Push local commits to the remote.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo path (default: .)"},
                "set_upstream": {"type": "boolean", "description": "Set upstream tracking (default: false)"},
            },
            "required": [],
        },
    ),
    _github_push,
)
