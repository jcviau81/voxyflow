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
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx

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

MAX_OUTPUT_CHARS = 10000


def _is_command_blocked(command: str) -> bool:
    """Check command against blocklist."""
    blocklist = _get_config("exec_blocklist", _DEFAULT_BLOCKLIST)
    cmd_lower = command.lower().strip()
    for blocked in blocklist:
        if blocked.lower() in cmd_lower:
            return True
    return False


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

    cwd = params.get("cwd")
    if cwd:
        cwd = str(Path(cwd).expanduser().resolve())
        if not Path(cwd).is_dir():
            return {"success": False, "error": f"Working directory does not exist: {cwd}"}

    timeout = params.get("timeout", 30)
    timeout = min(max(timeout, 1), 300)  # Clamp between 1s and 5min

    logger.info(f"[system.exec] Running: {command} (cwd={cwd}, timeout={timeout}s)")

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
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
    """Search the web via Brave Search API."""
    query = params.get("query", "").strip()
    if not query:
        return {"success": False, "error": "No search query provided"}

    count = min(max(params.get("count", 5), 1), 20)

    api_key = _get_config("brave_api_key", "") or os.environ.get("BRAVE_API_KEY", "")
    if not api_key:
        return {
            "success": False,
            "error": "Brave Search API key not configured. Set tools.brave_api_key in config.json or BRAVE_API_KEY env var.",
        }

    logger.info(f"[web.search] Searching: {query} (count={count})")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": count},
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "X-Subscription-Token": api_key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("web", {}).get("results", [])[:count]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
            })

        return {"success": True, "results": results, "count": len(results)}

    except httpx.HTTPStatusError as e:
        return {"success": False, "error": f"Brave API error: HTTP {e.response.status_code}"}
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

    resolved = Path(path_str).expanduser().resolve()

    if not _is_path_allowed(str(resolved)):
        return {"success": False, "error": f"Path not in allowed directories: {path_str}"}

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
# 6. file.list
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
