"""Test configuration — use a separate test database to avoid polluting production data.

This conftest patches the database engine AFTER import to redirect all DB writes
to a temporary test database, and runs the full schema init (including the raw
SQL ``kg_*`` tables) so KG-backed tests don't explode on a fresh CI box. The
production database is never touched.
"""

import os
import sys
import pytest

os.environ.setdefault("VOXYFLOW_LOG_DIR", "/tmp/voxyflow-test-logs")

TEST_DB_URL = "sqlite+aiosqlite:////tmp/voxyflow_test.db"
_DB_PATCH_STATE: dict[str, object] = {}


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "db: initialize and route app.database to the local pytest database",
    )


def _init_test_database_once():
    """Redirect the app's database engine to a test DB and create the full schema.

    The schema is created from a fresh file every session so CI runs start
    from a known-empty state instead of whatever leftover a previous process
    happened to create.
    """
    if _DB_PATCH_STATE.get("initialized"):
        return

    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    # Remove any leftover file so each CI session starts fresh.
    try:
        os.unlink("/tmp/voxyflow_test.db")
    except FileNotFoundError:
        pass

    import app.database as db_module

    test_engine = create_async_engine(TEST_DB_URL, echo=False)
    test_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    original_engine = db_module.engine
    original_session = db_module.async_session

    db_module.engine = test_engine
    db_module.async_session = test_session
    kg_module = sys.modules.get("app.services.knowledge_graph_service")
    if kg_module is not None:
        kg_module.async_session = test_session
        kg_module._kg_service = None
    _DB_PATCH_STATE.update({
        "initialized": True,
        "original_engine": original_engine,
        "original_session": original_session,
    })

    # Run the full schema init against the test DB (creates both the ORM
    # tables and the raw SQL kg_* tables that init_db sets up).
    asyncio.run(db_module.init_db())


@pytest.fixture(autouse=True)
def _use_test_database(request):
    """Opt-in DB setup for tests that really need app.database.

    Most backend unit tests exercise pure orchestration/LLM logic and do not
    touch the database. Initializing SQLite for every test makes those suites
    fragile when the local async SQLite driver is unavailable or slow, and it
    wastes several seconds even when it works.
    """
    if request.node.get_closest_marker("db") is None:
        yield
        return

    _init_test_database_once()
    yield


@pytest.fixture(autouse=True, scope="session")
def _restore_test_database():
    yield
    if not _DB_PATCH_STATE.get("initialized"):
        return
    import app.database as db_module
    db_module.engine = _DB_PATCH_STATE["original_engine"]
    db_module.async_session = _DB_PATCH_STATE["original_session"]
