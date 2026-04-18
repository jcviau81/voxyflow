"""System tools — real execution capabilities for Voxyflow.

These tools give Claude the ability to actually DO things on the local machine:
- Run shell commands (system.exec)
- Search the web (web.search)
- Fetch web pages (web.fetch)
- Read/write/list files (file.read, file.write, file.list)

Safety: configurable blocklists, allowed paths, and enable/disable flags
via config.json or environment variables.
"""

import asyncio
import fnmatch
import json
import logging
import os
import re
import shlex
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx

from app.config import VOXYFLOW_WORKSPACE_DIR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration loader
# ---------------------------------------------------------------------------

_CONFIG_CACHE: dict | None = None
_CONFIG_MTIME: float = 0

def _load_tools_config() -> dict:
    """Load tools config from config.json, with caching."""
    global _CONFIG_CACHE, _CONFIG_MTIME

    config_path = Path(__file__).parent.parent.parent / "config.json"
    if not config_path.exists():
        return {}

    try:
        mtime = config_path.stat().st_mtime
        if _CONFIG_CACHE is not None and _CONFIG_MTIME == mtime:
            return _CONFIG_CACHE

        with open(config_path) as f:
            data = json.load(f)
        _CONFIG_CACHE = data.get("tools", {})
        _CONFIG_MTIME = mtime
        return _CONFIG_CACHE
    except Exception as e:
        logger.warning(f"Failed to load tools config: {e}")
        return {}


def _get_config(key: str, default: Any = None) -> Any:
    cfg = _load_tools_config()
    return cfg.get(key, default)


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def _is_path_allowed(path_str: str) -> bool:
    """Check if a path is within allowed directories."""
    allowed = _get_config("allowed_paths", ["~", "/tmp"])
    resolved = Path(path_str).expanduser().resolve()

    for allowed_path in allowed:
        allowed_resolved = Path(allowed_path).expanduser().resolve()
        try:
            resolved.relative_to(allowed_resolved)
            return True
        except ValueError:
            continue

    return False


# Common shell builtins / utilities that workers sometimes pass as a "path"
# when they meant to run a command. Used by _looks_like_shell_command() to
# reject obvious misuses of file.write / file.patch before they pollute the
# workspace with files named after bash commands.
_SHELL_COMMAND_PREFIXES = {
    "mkdir", "rmdir", "rm", "cp", "mv", "touch", "ls", "ll", "cat",
    "echo", "cd", "pwd", "chmod", "chown", "ln", "find", "grep",
    "sed", "awk", "tar", "zip", "unzip", "curl", "wget", "git",
    "python", "python3", "pip", "pip3", "node", "npm", "npx",
    "yarn", "pnpm", "bash", "sh", "zsh", "export", "source",
    "systemctl", "docker", "kubectl", "make", "cmake",
}

# Characters that should never appear in a filesystem path but routinely
# show up when a model passes a shell command string as a `path` argument.
_SHELL_METACHARS = (";", "|", "&", "$", "`", ">", "<", "\n", "\r")


def _looks_like_shell_command(path_str: str) -> Optional[str]:
    """Return a human-readable reason if *path_str* looks like a shell command
    instead of a filesystem path, or None if it's acceptable.

    This catches the class of bug where workers (especially smaller models)
    hallucinate tool routing and pass things like ``"mkdir devices"`` or
    ``"git status"`` as the `path` argument to file.write/file.patch, which
    would otherwise silently create empty files with those literal names.
    """
    stripped = path_str.strip()
    if not stripped:
        return None  # caller already checks for empty

    # Shell metacharacters never belong in a normal path.
    for ch in _SHELL_METACHARS:
        if ch in stripped:
            return f"path contains shell metacharacter {ch!r} — use system.exec for shell commands, not file.write"

    # First whitespace-separated token — if it matches a known shell command
    # AND the rest of the string looks like arguments (has a space), it's
    # almost certainly a misrouted command.
    first, _, rest = stripped.partition(" ")
    if rest and first.lower() in _SHELL_COMMAND_PREFIXES:
        return (
            f"path starts with shell command {first!r} — this looks like a "
            f"shell command, not a file path. Use system.exec(command=...) "
            f"to run shell commands."
        )

    # Natural-language prose: 3+ whitespace-separated words, no slash, no
    # file extension. This catches cases like "Worker search restart
    # triggered" where a model passed a summary or status message as a path.
    if "/" not in stripped and "." not in stripped:
        tokens = stripped.split()
        if len(tokens) >= 3:
            return (
                "path looks like natural-language prose (multiple words, no "
                "'/' or extension) — not a file path. If you want to write a "
                "file, pass a real path like 'notes.md' or 'subdir/file.txt'."
            )

    return None


def _is_write_allowed(path_str: str) -> bool:
    """Check if a path is allowed for write operations.

    Applies stricter validation than _is_path_allowed():
    - Must pass the standard allowed_paths check first.
    - Must NOT be under any path listed in denied_write_paths, UNLESS the
      env var VOXYFLOW_DEV_TASK=1 is set (Voxyflow codebase dev tasks).

    This protects ~/voxyflow/ (the app codebase) from accidental writes by
    workers. Workers should write to ~/.voxyflow/workspace/ instead.
    Note: ~/.voxyflow (dot-voxyflow) is NOT affected by this restriction.
    """
    # Standard allowed_paths check
    if not _is_path_allowed(path_str):
        return False

    # Check denied_write_paths (defaults to protecting ~/voxyflow/ app dir)
    denied = _get_config("denied_write_paths", [])
    if not denied:
        return True

    resolved = Path(path_str).expanduser().resolve()

    for denied_path in denied:
        denied_resolved = Path(denied_path).expanduser().resolve()
        try:
            resolved.relative_to(denied_resolved)
            # Path is under a denied directory — check for explicit override
            if os.environ.get("VOXYFLOW_DEV_TASK", "").lower() in ("1", "true", "yes"):
                logger.info(
                    "[path.write] VOXYFLOW_DEV_TASK override: allowing write to "
                    f"protected path: {resolved}"
                )
                return True
            logger.warning(
                f"[path.write] BLOCKED write to protected path: {resolved} "
                "(Workers must write to ~/.voxyflow/workspace/ — "
                "set VOXYFLOW_DEV_TASK=1 only for Voxyflow codebase tasks)"
            )
            return False
        except ValueError:
            continue

    return True


# ---------------------------------------------------------------------------
# 1. system.exec
# ---------------------------------------------------------------------------

_DEFAULT_BLOCKLIST = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    "chmod -R 777 /",
    "chown -R",
    "> /dev/sda",
    "mv /* /dev/null",
    "wget | sh",
    "curl | sh",
    "wget | bash",
    "curl | bash",
]

# argv[0]s that are never acceptable. Checked against the resolved basename so
# `/sbin/mkfs.ext4`, `sudo mkfs`, or a quoted `"mk""fs"` argv all trip the gate.
_BINARY_BLOCKLIST = {"mkfs", "mkfs.ext4", "mkfs.ext3", "mkfs.xfs", "mkfs.btrfs"}

# Regex patterns applied to a canonicalised copy of the command. Canonicalise
# == strip shell quotes/backslash escapes, collapse whitespace, lowercase.
# This defeats the obvious bypasses (``r\m``, ``"rm"``, ``rm  -rf  /``) that
# the old substring blocklist missed.
_PATTERN_BLOCKLIST = [
    re.compile(r"\brm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r|--recursive\s+--force)\s+/(\s|$|\*)"),
    re.compile(r"\bdd\s+if="),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
    re.compile(r"\bchmod\s+-[a-z]*r[a-z]*\s+777\s+/\b"),
    re.compile(r"\bchown\s+-[a-z]*r[a-z]*\b"),
    re.compile(r">\s*/dev/sd[a-z]"),
    re.compile(r"\b(curl|wget)\b.+\|\s*(ba)?sh\b"),
    re.compile(r"\bmv\s+/\*?\s+/dev/null"),
]

MAX_OUTPUT_CHARS = 100000


def _canonicalize_command(command: str) -> str:
    """Return a normalised representation of *command* that defeats quoting
    and escape tricks used to bypass the substring blocklist.

    We parse with shlex (which strips shell quotes and backslash escapes),
    fall back to the raw string if parsing fails (e.g. unbalanced quotes —
    which on a real shell would also fail), and collapse whitespace.
    """
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        parts = command.split()
    joined = " ".join(parts)
    return re.sub(r"\s+", " ", joined).strip().lower()


def _binary_basename(token: str) -> str:
    """Return the trailing component of ``token`` without any directory or
    version qualifier (e.g. ``/sbin/mkfs.ext4`` → ``mkfs.ext4``)."""
    return Path(token.strip()).name.lower()


def _is_command_blocked(command: str) -> bool:
    """Check a command against the safety filters.

    Three layers, short-circuiting:
      1. Config substring list (back-compat, unchanged).
      2. argv-level binary blocklist (catches ``sudo mkfs.ext4 /dev/sda``).
      3. Regex patterns over the canonicalised command (defeats escapes).
    """
    blocklist = _get_config("exec_blocklist", _DEFAULT_BLOCKLIST)
    cmd_lower = command.lower().strip()
    for blocked in blocklist:
        if blocked.lower() in cmd_lower:
            return True

    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        argv = command.split()

    for token in argv:
        if _binary_basename(token) in _BINARY_BLOCKLIST:
            return True

    canonical = _canonicalize_command(command)
    for pattern in _PATTERN_BLOCKLIST:
        if pattern.search(canonical):
            return True

    return False


def _resolve_exec_cwd(cwd: str | None) -> tuple[str, str | None]:
    """Resolve the working directory for ``system.exec`` and confine it.

    Commands must run under ``VOXYFLOW_WORKSPACE_DIR`` (the workers' sandbox).
    Set ``VOXYFLOW_DEV_TASK=1`` to opt into running against the Voxyflow
    codebase itself (matches the write-path escape hatch).

    Returns ``(resolved_cwd, error)``. If ``error`` is non-None, the caller
    must surface it and abort.
    """
    workspace = Path(VOXYFLOW_WORKSPACE_DIR).expanduser().resolve()

    if cwd:
        resolved = Path(cwd).expanduser().resolve()
        if not resolved.is_dir():
            return str(resolved), f"Working directory does not exist: {resolved}"
    else:
        resolved = workspace

    dev_task = os.environ.get("VOXYFLOW_DEV_TASK", "").lower() in ("1", "true", "yes")
    if dev_task:
        return str(resolved), None

    try:
        resolved.relative_to(workspace)
    except ValueError:
        return str(resolved), (
            f"cwd must be under the workspace ({workspace}); got {resolved}. "
            "Set VOXYFLOW_DEV_TASK=1 only for Voxyflow codebase tasks."
        )
    return str(resolved), None


def _truncate(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    """Truncate text if too long, return (text, was_truncated)."""
    if len(text) <= max_chars:
        return text, False
    half = max_chars // 2
    return (
        text[:half]
        + f"\n\n... [{len(text) - max_chars} chars truncated] ...\n\n"
        + text[-half:],
        True,
    )


async def system_exec(params: dict) -> dict:
    """Run a shell command on the local machine."""
    if not _get_config("exec_enabled", True):
        return {"success": False, "error": "system.exec is disabled in config"}

    command = params.get("command", "").strip()
    if not command:
        return {"success": False, "error": "No command provided"}

    if _is_command_blocked(command):
        logger.warning(f"[system.exec] BLOCKED dangerous command: {command}")
        return {"success": False, "error": f"Command blocked by safety filter: {command}"}

    cwd, cwd_err = _resolve_exec_cwd(params.get("cwd"))
    if cwd_err:
        logger.warning(f"[system.exec] BLOCKED cwd: {cwd_err}")
        return {"success": False, "error": cwd_err}

    timeout = params.get("timeout", 30)
    timeout = min(max(timeout, 1), 300)  # Clamp between 1s and 5min

    logger.info(f"[system.exec] Running: {command} (cwd={cwd}, timeout={timeout}s)")

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *shlex.split(command),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env={**os.environ},
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        duration_ms = int((time.monotonic() - start) * 1000)

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        stdout, stdout_truncated = _truncate(stdout)
        stderr, stderr_truncated = _truncate(stderr)

        return {
            "success": True,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": proc.returncode,
            "duration_ms": duration_ms,
            "truncated": stdout_truncated or stderr_truncated,
        }

    except asyncio.TimeoutError:
        duration_ms = int((time.monotonic() - start) * 1000)
        proc.kill()
        return {
            "success": False,
            "error": f"Command timed out after {timeout}s",
            "duration_ms": duration_ms,
        }
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": False,
            "error": str(e),
            "duration_ms": duration_ms,
        }


# ---------------------------------------------------------------------------
# 2. web.search
# ---------------------------------------------------------------------------

async def web_search(params: dict) -> dict:
    """Search the web via DuckDuckGo (no API key required)."""
    import re as _re
    import urllib.parse as _urlparse

    query = params.get("query", "").strip()
    if not query:
        return {"success": False, "error": "No search query provided"}

    count = min(max(params.get("count", 5), 1), 20)
    region = params.get("region", "wt-wt")

    logger.info(f"[web.search] DuckDuckGo: {query} (count={count})")

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query, "kl": region},
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            resp.raise_for_status()
            html = resp.text

        results = []
        # Parse result titles + URLs
        title_url_pairs = _re.findall(
            r'<a[^>]+class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            html, _re.DOTALL
        )
        # Parse snippets
        raw_snippets = _re.findall(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            html, _re.DOTALL
        )

        for i, (raw_url, raw_title) in enumerate(title_url_pairs[:count]):
            # Decode DDG redirect
            url = raw_url
            if "duckduckgo.com/l/" in url or url.startswith("//"):
                m = _re.search(r"uddg=([^&]+)", url)
                if m:
                    url = _urlparse.unquote(m.group(1))

            title = _re.sub(r"<[^>]+>", "", raw_title).strip()
            snippet = ""
            if i < len(raw_snippets):
                snippet = _re.sub(r"<[^>]+>", "", raw_snippets[i]).strip()[:300]

            if title and url:
                results.append({"title": title, "url": url, "snippet": snippet})

        return {"success": True, "results": results, "count": len(results)}

    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"DuckDuckGo error: HTTP {e.response.status_code}"}
    except Exception as e:
        return {"success": False, "error": f"Search failed: {str(e)}"}


# ---------------------------------------------------------------------------
# 3. web.fetch
# ---------------------------------------------------------------------------

def _extract_readable_content(html: str, max_chars: int = 5000) -> tuple[str, str]:
    """Extract readable content from HTML, return (content, title)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        # Fallback: strip tags naively
        import re
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars], ""

    soup = BeautifulSoup(html, "html.parser")

    # Extract title
    title = ""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)

    # Remove unwanted elements
    for tag in soup.find_all(["script", "style", "nav", "header", "footer",
                               "aside", "noscript", "iframe", "svg"]):
        tag.decompose()

    # Try to find main content area
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find(attrs={"role": "main"})
        or soup.find("div", class_=lambda c: c and "content" in c.lower() if c else False)
        or soup.body
        or soup
    )

    # Get text
    text = main.get_text(separator="\n", strip=True)

    # Clean up excessive whitespace
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    text = "\n".join(lines)

    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[... truncated]"

    return text, title


async def web_fetch(params: dict) -> dict:
    """Fetch and extract readable content from a URL."""
    url = params.get("url", "").strip()
    if not url:
        return {"success": False, "error": "No URL provided"}

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    max_chars = params.get("max_chars", 5000)
    max_chars = min(max(max_chars, 100), 50000)

    logger.info(f"[web.fetch] Fetching: {url} (max_chars={max_chars})")

    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Voxyflow/1.0; +https://voxyflow.dev)",
            },
        ) as client:
            resp = await client.get(url)

        content, title = _extract_readable_content(resp.text, max_chars)

        return {
            "success": True,
            "content": content,
            "title": title,
            "url": str(resp.url),  # Final URL after redirects
            "status_code": resp.status_code,
        }

    except httpx.TimeoutException:
        return {"success": False, "error": f"Request timed out fetching {url}"}
    except Exception as e:
        return {"success": False, "error": f"Fetch failed: {str(e)}"}


# ---------------------------------------------------------------------------
# 4. file.read
# ---------------------------------------------------------------------------

async def file_read(params: dict) -> dict:
    """Read a file from the filesystem."""
    path_str = params.get("path", "").strip()
    if not path_str:
        return {"success": False, "error": "No file path provided"}

    resolved = Path(path_str).expanduser().resolve()

    if not _is_path_allowed(str(resolved)):
        return {"success": False, "error": f"Path not in allowed directories: {path_str}"}

    if not resolved.exists():
        return {"success": False, "error": f"File not found: {path_str}"}

    if not resolved.is_file():
        return {"success": False, "error": f"Not a file: {path_str}"}

    offset = params.get("offset", 1)  # 1-indexed line number
    limit = params.get("limit")

    logger.info(f"[file.read] Reading: {resolved} (offset={offset}, limit={limit})")

    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
        lines = text.split("\n")
        total_lines = len(lines)

        # Apply offset (1-indexed)
        start = max(0, (offset or 1) - 1)
        if limit:
            end = start + limit
        else:
            end = total_lines

        selected = lines[start:end]
        content = "\n".join(selected)
        truncated = end < total_lines

        content, was_truncated = _truncate(content)
        truncated = truncated or was_truncated

        return {
            "success": True,
            "content": content,
            "lines": len(selected),
            "total_lines": total_lines,
            "truncated": truncated,
        }

    except Exception as e:
        return {"success": False, "error": f"Read failed: {str(e)}"}


# ---------------------------------------------------------------------------
# 5. file.write
# ---------------------------------------------------------------------------

async def file_write(params: dict) -> dict:
    """Write content to a file."""
    path_str = params.get("path", "").strip()
    if not path_str:
        return {"success": False, "error": "No file path provided"}

    content = params.get("content", "")
    mode = params.get("mode", "overwrite")

    command_hint = _looks_like_shell_command(path_str)
    if command_hint:
        logger.warning(f"[file.write] Rejected command-like path {path_str!r}: {command_hint}")
        return {"success": False, "error": f"Invalid path {path_str!r}: {command_hint}"}

    resolved = Path(path_str).expanduser().resolve()

    if not _is_write_allowed(str(resolved)):
        return {"success": False, "error": f"Path not allowed for writes: {path_str} — workers must write to ~/.voxyflow/workspace/ (set VOXYFLOW_DEV_TASK=1 for Voxyflow codebase tasks)"}

    logger.info(f"[file.write] Writing: {resolved} (mode={mode}, {len(content)} chars)")

    try:
        # Create parent directories if needed
        resolved.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append":
            with open(resolved, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            resolved.write_text(content, encoding="utf-8")

        return {
            "success": True,
            "path": str(resolved),
            "bytes_written": len(content.encode("utf-8")),
        }

    except Exception as e:
        return {"success": False, "error": f"Write failed: {str(e)}"}


# ---------------------------------------------------------------------------
# 5b. file.patch
# ---------------------------------------------------------------------------

async def file_patch(params: dict) -> dict:
    """Replace exact text in a file (surgical edit, no heredoc needed)."""
    path_str = params.get("path", "").strip()
    if not path_str:
        return {"success": False, "error": "No file path provided"}

    old_str = params.get("old", "")
    new_str = params.get("new", "")

    if not old_str:
        return {"success": False, "error": "No old string provided"}

    command_hint = _looks_like_shell_command(path_str)
    if command_hint:
        logger.warning(f"[file.patch] Rejected command-like path {path_str!r}: {command_hint}")
        return {"success": False, "error": f"Invalid path {path_str!r}: {command_hint}"}

    resolved = Path(path_str).expanduser().resolve()

    if not _is_write_allowed(str(resolved)):
        return {"success": False, "error": f"Path not allowed for writes: {path_str} — workers must write to ~/.voxyflow/workspace/ (set VOXYFLOW_DEV_TASK=1 for Voxyflow codebase tasks)"}

    if not resolved.exists():
        return {"success": False, "error": f"File not found: {path_str}"}

    if not resolved.is_file():
        return {"success": False, "error": f"Not a file: {path_str}"}

    logger.info(f"[file.patch] Patching: {resolved} (old={len(old_str)} chars, new={len(new_str)} chars)")

    try:
        content = resolved.read_text(encoding="utf-8")

        if old_str not in content:
            return {"success": False, "error": f"String not found in {path_str}", "path": str(resolved)}

        count = content.count(old_str)
        new_content = content.replace(old_str, new_str, 1)  # replace first occurrence only

        resolved.write_text(new_content, encoding="utf-8")

        return {
            "success": True,
            "path": str(resolved),
            "occurrences_found": count,
            "replaced": 1,
        }

    except Exception as e:
        return {"success": False, "error": f"Patch failed: {str(e)}"}


# ---------------------------------------------------------------------------
# 6. file.list
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 7. git tools
# ---------------------------------------------------------------------------

_DEFAULT_GIT_PATH = os.path.expanduser("~")


async def _run_git(args: list[str], cwd: str, timeout: int = 30) -> dict:
    """Helper to run a git command and return structured output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            return {"success": False, "error": stderr.strip() or f"git exited with code {proc.returncode}"}
        return {"success": True, "result": stdout.strip()}
    except asyncio.TimeoutError:
        return {"success": False, "error": f"git command timed out after {timeout}s"}
    except FileNotFoundError:
        return {"success": False, "error": "git is not installed or not in PATH"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def git_status(params: dict) -> dict:
    """Run git status in a given path."""
    cwd = params.get("path", _DEFAULT_GIT_PATH)
    cwd = str(Path(cwd).expanduser().resolve())
    return await _run_git(["status"], cwd)


async def git_log(params: dict) -> dict:
    """Run git log --oneline."""
    cwd = params.get("path", _DEFAULT_GIT_PATH)
    cwd = str(Path(cwd).expanduser().resolve())
    limit = str(params.get("limit", 20))
    return await _run_git(["log", "--oneline", f"-{limit}"], cwd)


async def git_diff(params: dict) -> dict:
    """Run git diff (or git diff --staged)."""
    cwd = params.get("path", _DEFAULT_GIT_PATH)
    cwd = str(Path(cwd).expanduser().resolve())
    staged = params.get("staged", False)
    args = ["diff", "--staged"] if staged else ["diff", "HEAD"]
    return await _run_git(args, cwd)


async def git_branches(params: dict) -> dict:
    """List all git branches."""
    cwd = params.get("path", _DEFAULT_GIT_PATH)
    cwd = str(Path(cwd).expanduser().resolve())
    return await _run_git(["branch", "-a"], cwd)


async def git_commit(params: dict) -> dict:
    """Stage all changes and commit with a message."""
    cwd = params.get("path", _DEFAULT_GIT_PATH)
    cwd = str(Path(cwd).expanduser().resolve())
    message = params.get("message", "").strip()
    if not message:
        return {"success": False, "error": "No commit message provided"}

    # Stage all
    add_result = await _run_git(["add", "-A"], cwd)
    if not add_result.get("success"):
        return add_result

    # Commit
    return await _run_git(["commit", "-m", message], cwd)


# ---------------------------------------------------------------------------
# 8. tmux tools
# ---------------------------------------------------------------------------

async def _run_tmux(args: list[str], timeout: int = 10) -> dict:
    """Helper to run a tmux command and return structured output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "tmux", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            return {"success": False, "error": stderr.strip() or f"tmux exited with code {proc.returncode}"}
        return {"success": True, "result": stdout.strip()}
    except asyncio.TimeoutError:
        return {"success": False, "error": f"tmux command timed out after {timeout}s"}
    except FileNotFoundError:
        return {"success": False, "error": "tmux is not installed or not in PATH"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def tmux_list(params: dict) -> dict:
    """List all tmux sessions."""
    return await _run_tmux(["ls"])


async def tmux_run(params: dict) -> dict:
    """Run a command in a named tmux session (creates if doesn't exist)."""
    session = params.get("session", "").strip()
    command = params.get("command", "").strip()
    if not session:
        return {"success": False, "error": "No session name provided"}
    if not command:
        return {"success": False, "error": "No command provided"}

    # Check if session exists
    check = await _run_tmux(["has-session", "-t", session])
    if check.get("success"):
        # Session exists — send command
        result = await _run_tmux(["send-keys", "-t", session, command, "Enter"])
        if result.get("success"):
            result["result"] = f"Sent command to existing session '{session}'"
        return result
    else:
        # Create new session with command
        result = await _run_tmux(["new-session", "-d", "-s", session, command])
        if result.get("success"):
            result["result"] = f"Created session '{session}' running: {command}"
        return result


async def tmux_send(params: dict) -> dict:
    """Send keys to a tmux pane."""
    session = params.get("session", "").strip()
    keys = params.get("keys", "").strip()
    if not session:
        return {"success": False, "error": "No session name provided"}
    if not keys:
        return {"success": False, "error": "No keys provided"}
    return await _run_tmux(["send-keys", "-t", session, keys, "Enter"])


async def tmux_capture(params: dict) -> dict:
    """Capture output from a tmux pane."""
    session = params.get("session", "").strip()
    if not session:
        return {"success": False, "error": "No session name provided"}

    # Capture pane content to stdout
    return await _run_tmux(["capture-pane", "-t", session, "-p"])


async def tmux_new(params: dict) -> dict:
    """Create a new named tmux session."""
    session = params.get("session", "").strip()
    if not session:
        return {"success": False, "error": "No session name provided"}

    command = params.get("command", "").strip()
    args = ["new-session", "-d", "-s", session]
    if command:
        args.append(command)

    result = await _run_tmux(args)
    if result.get("success"):
        result["result"] = f"Created session '{session}'" + (f" running: {command}" if command else "")
    return result


async def tmux_kill(params: dict) -> dict:
    """Kill a tmux session."""
    session = params.get("session", "").strip()
    if not session:
        return {"success": False, "error": "No session name provided"}
    result = await _run_tmux(["kill-session", "-t", session])
    if result.get("success"):
        result["result"] = f"Killed session '{session}'"
    return result


# ---------------------------------------------------------------------------
# 6. file.list (original numbering preserved)
# ---------------------------------------------------------------------------

async def file_list(params: dict) -> dict:
    """List files in a directory."""
    path_str = params.get("path", "").strip()
    if not path_str:
        return {"success": False, "error": "No directory path provided"}

    resolved = Path(path_str).expanduser().resolve()

    if not _is_path_allowed(str(resolved)):
        return {"success": False, "error": f"Path not in allowed directories: {path_str}"}

    if not resolved.exists():
        return {"success": False, "error": f"Directory not found: {path_str}"}

    if not resolved.is_dir():
        return {"success": False, "error": f"Not a directory: {path_str}"}

    pattern = params.get("pattern", "*")
    recursive = params.get("recursive", False)

    logger.info(f"[file.list] Listing: {resolved} (pattern={pattern}, recursive={recursive})")

    try:
        entries = []
        if recursive:
            items = sorted(resolved.rglob(pattern))
        else:
            items = sorted(resolved.glob(pattern))

        # Limit to 500 entries to avoid overwhelming output
        for item in items[:500]:
            try:
                stat = item.stat()
                entries.append({
                    "name": item.name,
                    "path": str(item),
                    "size": stat.st_size,
                    "is_dir": item.is_dir(),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
            except (PermissionError, OSError):
                continue

        return {
            "success": True,
            "entries": entries,
            "count": len(entries),
            "truncated": len(items) > 500,
        }

    except Exception as e:
        return {"success": False, "error": f"List failed: {str(e)}"}
