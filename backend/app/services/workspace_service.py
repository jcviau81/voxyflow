"""Workspace service — managed file storage for Voxy.

All paths stored/returned are RELATIVE to VOXYFLOW_DIR.
Security: rejects any path with '..' components to prevent traversal.
"""

import json
import logging
import os
from pathlib import Path

from sqlalchemy import text
from app.database import async_session

logger = logging.getLogger(__name__)

VOXYFLOW_DIR = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/voxyflow")))


class WorkspaceService:
    """Manages file operations within the workspace directory."""

    def __init__(self):
        self._workspace_rel = "workspace"  # default

    async def _load_workspace_path(self) -> str:
        """Load workspace_path from settings DB."""
        try:
            async with async_session() as session:
                result = await session.execute(
                    text("SELECT value FROM app_settings WHERE key = 'app_settings'")
                )
                row = result.fetchone()
                if row:
                    data = json.loads(row[0])
                    return data.get("workspace_path", "workspace")
        except Exception as e:
            logger.warning("Failed to load workspace_path from DB: %s", e)
        return "workspace"

    def _resolve_workspace(self, workspace_path: str) -> Path:
        """Resolve workspace_path to an absolute path."""
        p = Path(workspace_path)
        if p.is_absolute():
            return p
        return VOXYFLOW_DIR / workspace_path

    async def get_workspace_path(self) -> Path:
        """Returns the resolved absolute path of the workspace."""
        rel = await self._load_workspace_path()
        return self._resolve_workspace(rel)

    async def ensure_workspace(self) -> Path:
        """Creates the workspace dir if it doesn't exist. Returns the path."""
        ws = await self.get_workspace_path()
        ws.mkdir(parents=True, exist_ok=True)
        logger.info("Workspace directory ensured: %s", ws)
        return ws

    def _validate_path(self, relative_path: str) -> None:
        """Reject paths with '..' components."""
        parts = Path(relative_path).parts
        if ".." in parts:
            raise ValueError(f"Path traversal not allowed: {relative_path}")
        if Path(relative_path).is_absolute():
            raise ValueError(f"Absolute paths not allowed: {relative_path}")

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a relative path against VOXYFLOW_DIR."""
        self._validate_path(relative_path)
        return VOXYFLOW_DIR / relative_path

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
            rel = entry.relative_to(VOXYFLOW_DIR)
            entries.append({
                "name": entry.name,
                "path": str(rel),
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else 0,
            })
        return entries

    async def read_file(self, relative_path: str) -> str:
        """Read a file from workspace. Path is relative to VOXYFLOW_DIR."""
        path = self.resolve_path(relative_path)
        ws = await self.get_workspace_path()
        # Ensure the resolved path is within workspace
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
        # Ensure the resolved path is within workspace
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
                rel = str(entry.relative_to(VOXYFLOW_DIR))
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
