"""Two workspaces must never share a sandbox ``local_path``.

``local_path`` is the worker cwd (see ``services/workspace_paths``), so two rows
holding the same sandbox directory means workers of workspace B read and write
workspace A's files — and ``delete_workspace`` ``_rmtree``s that directory,
taking the other workspace's files with it.

The collision is reachable because the duplicate-title guard in
``create_workspace`` ignores archived workspaces, and because a rename
deliberately leaves ``local_path`` in place (CLAUDE.md §5a).
"""

import os
import sys
from uuid import uuid4

import pytest
from sqlalchemy import select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.database as db_module  # noqa: E402
from app.database import Workspace  # noqa: E402
from app.models.workspace import WorkspaceCreate  # noqa: E402
from app.routes.workspaces.crud import create_workspace  # noqa: E402

pytestmark = pytest.mark.db


async def _create(title: str, local_path: str | None = None) -> Workspace:
    async with db_module.async_session() as db:
        return await create_workspace(
            WorkspaceCreate(title=title, local_path=local_path), db=db
        )


async def _archive(workspace_id: str) -> None:
    async with db_module.async_session() as db:
        ws = await db.get(Workspace, workspace_id)
        ws.status = "archived"
        await db.commit()


@pytest.mark.asyncio
async def test_archived_workspace_does_not_donate_its_directory():
    """Archive "Recipes", create "Recipes" again — the second must not reuse the path."""
    title = f"Recipes {uuid4().hex[:8]}"

    first = await _create(title)
    await _archive(first.id)
    second = await _create(title)

    assert second.local_path != first.local_path, (
        "the new workspace reused the archived one's directory — its workers "
        "would read/write those files, and deleting it would wipe them"
    )
    assert second.local_path.endswith(second.id[:8])


@pytest.mark.asyncio
async def test_renamed_workspace_keeps_its_directory_reserved():
    """Rename X off "Foo", create a new "Foo" — X's directory stays X's."""
    title = f"Foo {uuid4().hex[:8]}"

    original = await _create(title)
    async with db_module.async_session() as db:
        ws = await db.get(Workspace, original.id)
        ws.title = f"Bar {uuid4().hex[:8]}"
        await db.commit()

    newcomer = await _create(title)
    assert newcomer.local_path != original.local_path

    # The rename must not have moved the original off its directory either.
    async with db_module.async_session() as db:
        still = await db.get(Workspace, original.id)
    assert still.local_path == original.local_path


@pytest.mark.asyncio
async def test_explicit_shared_path_is_still_allowed(tmp_path):
    """Deliberately pointing two workspaces at one checkout stays legal.

    Real installs do this (two workspaces on one repo). Only the auto-generated
    slug is disambiguated, and delete_workspace never rmtree's outside the
    sandbox, so an external share is safe.
    """
    shared = str(tmp_path / "sketchyapi")

    a = await _create(f"A {uuid4().hex[:8]}", local_path=shared)
    b = await _create(f"B {uuid4().hex[:8]}", local_path=shared)

    assert a.local_path == b.local_path == shared


@pytest.mark.asyncio
async def test_sandbox_local_paths_are_unique_across_all_workspaces():
    async with db_module.async_session() as db:
        paths = [
            p for (p,) in (await db.execute(select(Workspace.local_path))).all()
            if p and "/sandbox/workspaces/" in p
        ]
    assert len(paths) == len(set(paths)), "duplicate sandbox local_path in the DB"
