"""Sandbox service — managed file storage for Voxy workers.

Sandbox root: ~/.voxyflow/sandbox/ (VOXYFLOW_SANDBOX_DIR)
Per-workspace area: ~/.voxyflow/sandbox/workspaces/<workspace-slug>/
Security: rejects any path with '..' components to prevent traversal.
"""

import logging
import shutil
from pathlib import Path

from app.config import VOXYFLOW_SANDBOX_DIR

logger = logging.getLogger(__name__)


def migrate_legacy_projects_subdir() -> int:
    """Merge ``sandbox/projects/*`` into ``sandbox/workspaces/`` and remove the
    legacy parent dir when empty.

    The standalone migration script (``scripts/migrate_project_to_workspace.py``)
    only renames the parent dir when the target doesn't exist. When both
    co-existed because of a partial run, entries kept being written under the
    old name. This helper merges them safely: existing target entries win, so
    nothing is overwritten.

    Idempotent — returns count of entries moved (0 on a clean tree).
    """
    src_root = VOXYFLOW_SANDBOX_DIR / "projects"
    if not src_root.exists():
        return 0
    dst_root = VOXYFLOW_SANDBOX_DIR / "workspaces"
    dst_root.mkdir(parents=True, exist_ok=True)
    moved = 0
    for entry in list(src_root.iterdir()):
        target = dst_root / entry.name
        if target.exists():
            continue
        try:
            entry.rename(target)
            moved += 1
        except OSError:
            continue
    try:
        src_root.rmdir()
    except OSError:
        pass
    return moved


class SandboxService:
    """Manages file operations within the workers' sandbox directory."""

    def __init__(self):
        self._sandbox_root = VOXYFLOW_SANDBOX_DIR

    @property
    def sandbox_root(self) -> Path:
        return self._sandbox_root

    async def get_sandbox_path(self) -> Path:
        """Returns the resolved absolute path of the sandbox root."""
        return self._sandbox_root

    async def ensure_sandbox(self) -> Path:
        """Creates the sandbox dir if it doesn't exist. Returns the path."""
        self._sandbox_root.mkdir(parents=True, exist_ok=True)
        logger.info("Sandbox directory ensured: %s", self._sandbox_root)
        return self._sandbox_root

    def get_workspace_sandbox(self, workspace_name: str) -> Path:
        """Get the sandbox directory for a specific workspace (by slugified name)."""
        safe_name = self._slugify(workspace_name)
        return self._sandbox_root / "workspaces" / safe_name

    def ensure_workspace_sandbox(self, workspace_name: str) -> Path:
        """Create and return the sandbox directory for a workspace."""
        ws = self.get_workspace_sandbox(workspace_name)
        ws.mkdir(parents=True, exist_ok=True)
        logger.info("Workspace sandbox ensured: %s", ws)
        return ws

    def _slugify(self, name: str) -> str:
        """Convert workspace name to a safe directory name."""
        import re
        slug = name.strip().lower()
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[\s_]+', '-', slug)
        slug = slug.strip('-')
        return slug or 'unnamed'

    def _validate_path(self, relative_path: str) -> None:
        """Reject paths with '..' components or absolute paths (fast syntactic check)."""
        parts = Path(relative_path).parts
        if ".." in parts:
            raise ValueError(f"Path traversal not allowed: {relative_path}")
        if Path(relative_path).is_absolute():
            raise ValueError(f"Absolute paths not allowed: {relative_path}")

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a relative path against the sandbox root.

        Uses ``Path.resolve()`` to collapse symlinks and dot segments, then asserts
        the result is inside the sandbox root. Defends against symlink-based
        escapes that syntactic checks alone would miss.
        """
        self._validate_path(relative_path)
        root = self._sandbox_root.resolve()
        candidate = (self._sandbox_root / relative_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise ValueError(f"Path escapes sandbox root: {relative_path}")
        return candidate

    async def list_files(self, subdir: str = "") -> list[dict]:
        """List files and directories in sandbox (or subdirectory)."""
        ws = await self.get_sandbox_path()
        target = ws
        if subdir:
            self._validate_path(subdir)
            target = ws / subdir

        if not target.exists():
            return []

        entries = []
        for entry in sorted(target.iterdir()):
            rel = entry.relative_to(ws)
            entries.append({
                "name": entry.name,
                "path": str(rel),
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else 0,
            })
        return entries

    async def read_file(self, relative_path: str) -> str:
        """Read a file from sandbox. Path is relative to sandbox root."""
        path = self.resolve_path(relative_path)
        ws = await self.get_sandbox_path()
        try:
            path.resolve().relative_to(ws.resolve())
        except ValueError:
            raise ValueError(f"Path is outside sandbox: {relative_path}")
        if not path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        return path.read_text(encoding="utf-8")

    async def write_file(self, relative_path: str, content: str) -> str:
        """Write a file to sandbox. Returns the relative path."""
        path = self.resolve_path(relative_path)
        ws = await self.get_sandbox_path()
        try:
            path.resolve(strict=False).relative_to(ws.resolve())
        except ValueError:
            raise ValueError(f"Path is outside sandbox: {relative_path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(Path(relative_path))

    async def delete_file(self, relative_path: str) -> None:
        """Delete a file from sandbox."""
        path = self.resolve_path(relative_path)
        ws = await self.get_sandbox_path()
        try:
            path.resolve().relative_to(ws.resolve())
        except ValueError:
            raise ValueError(f"Path is outside sandbox: {relative_path}")
        if not path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        if path.is_dir():
            import shutil
            shutil.rmtree(path)
        else:
            path.unlink()

    async def get_tree(self, subdir: str = "") -> list[dict]:
        """Get full directory tree (recursive)."""
        ws = await self.get_sandbox_path()
        target = ws
        if subdir:
            self._validate_path(subdir)
            target = ws / subdir

        if not target.exists():
            return []

        def _walk(directory: Path) -> list[dict]:
            entries = []
            for entry in sorted(directory.iterdir()):
                rel = str(entry.relative_to(ws))
                node: dict = {
                    "name": entry.name,
                    "path": rel,
                    "is_dir": entry.is_dir(),
                }
                if entry.is_dir():
                    node["children"] = _walk(entry)
                else:
                    node["size"] = entry.stat().st_size
                entries.append(node)
            return entries

        return _walk(target)


# Singleton
_sandbox_service: SandboxService | None = None


def get_sandbox_service() -> SandboxService:
    global _sandbox_service
    if _sandbox_service is None:
        _sandbox_service = SandboxService()
    return _sandbox_service
