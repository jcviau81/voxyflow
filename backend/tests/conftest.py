"""Test configuration — use a separate test database to avoid polluting production data.

This conftest patches the database engine AFTER import to redirect all DB writes
to a temporary test database, and runs the full schema init (including the raw
SQL ``kg_*`` tables) so KG-backed tests don't explode on a fresh CI box. The
production database is never touched.
"""

import asyncio
import os
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

TEST_DB_URL = "sqlite+aiosqlite:////tmp/voxyflow_test.db"


@pytest.fixture(autouse=True, scope="session")
def _use_test_database():
    """Redirect the app's database engine to a test DB and create the full schema.

    The schema is created from a fresh file every session so CI runs start
    from a known-empty state instead of whatever leftover a previous process
    happened to create.
    """
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

    # Run the full schema init against the test DB (creates both the ORM
    # tables and the raw SQL kg_* tables that init_db sets up).
    asyncio.run(db_module.init_db())

    yield

    db_module.engine = original_engine
    db_module.async_session = original_session

