"""Workspace service — managed file storage for Voxy.

Workspace root: ~/.voxyflow/workspace/ (VOXYFLOW_WORKSPACE_DIR)
Projects: ~/.voxyflow/workspace/<project-name>/
Security: rejects any path with '..' components to prevent traversal.
"""

import json
import logging
import os
from pathlib import Path

from sqlalchemy import text
from app.database import async_session
from app.config import VOXYFLOW_WORKSPACE_DIR

logger = logging.getLogger(__name__)


class WorkspaceService:
    """Manages file operations within the workspace directory."""

    def __init__(self):
        self._workspace_root = VOXYFLOW_WORKSPACE_DIR

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    async def get_workspace_path(self) -> Path:
        """Returns the resolved absolute path of the workspace root."""
        return self._workspace_root

    async def ensure_workspace(self) -> Path:
        """Creates the workspace dir if it doesn't exist. Returns the path."""
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        logger.info("Workspace directory ensured: %s", self._workspace_root)
        return self._workspace_root

    def get_project_workspace(self, project_name: str) -> Path:
        """Get the workspace directory for a specific project."""
        safe_name = self._slugify(project_name)
        return self._workspace_root / "projects" / safe_name

    def ensure_project_workspace(self, project_name: str) -> Path:
        """Create and return the workspace directory for a project."""
        ws = self.get_project_workspace(project_name)
        ws.mkdir(parents=True, exist_ok=True)
        logger.info("Project workspace ensured: %s", ws)
        return ws

    def _slugify(self, name: str) -> str:
        """Convert project name to a safe directory name."""
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
        """Resolve a relative path against the workspace root.

        Uses ``Path.resolve()`` to collapse symlinks and dot segments, then asserts
        the result is inside the workspace root. Defends against symlink-based
        escapes that syntactic checks alone would miss.
        """
        self._validate_path(relative_path)
        root = self._workspace_root.resolve()
        candidate = (self._workspace_root / relative_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise ValueError(f"Path escapes workspace root: {relative_path}")
        return candidate

    async def list_files(self, subdir: str = "") -> list[dict]:
        """List files and directories in workspace (or subdirectory)."""
        ws = await self.get_workspace_path()
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
        """Read a file from workspace. Path is relative to workspace root."""
        path = self.resolve_path(relative_path)
        ws = await self.get_workspace_path()
        try:
            path.resolve().relative_to(ws.resolve())
        except ValueError:
            raise ValueError(f"Path is outside workspace: {relative_path}")
        if not path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        return path.read_text(encoding="utf-8")

    async def write_file(self, relative_path: str, content: str) -> str:
        """Write a file to workspace. Returns the relative path."""
        path = self.resolve_path(relative_path)
        ws = await self.get_workspace_path()
        try:
            path.resolve(strict=False).relative_to(ws.resolve())
        except ValueError:
            raise ValueError(f"Path is outside workspace: {relative_path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(Path(relative_path))

    async def delete_file(self, relative_path: str) -> None:
        """Delete a file from workspace."""
        path = self.resolve_path(relative_path)
        ws = await self.get_workspace_path()
        try:
            path.resolve().relative_to(ws.resolve())
        except ValueError:
            raise ValueError(f"Path is outside workspace: {relative_path}")
        if not path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        if path.is_dir():
            import shutil
            shutil.rmtree(path)
        else:
            path.unlink()

    async def get_tree(self, subdir: str = "") -> list[dict]:
        """Get full directory tree (recursive)."""
        ws = await self.get_workspace_path()
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
_workspace_service: WorkspaceService | None = None


def get_workspace_service() -> WorkspaceService:
    global _workspace_service
    if _workspace_service is None:
        _workspace_service = WorkspaceService()
    return _workspace_service
