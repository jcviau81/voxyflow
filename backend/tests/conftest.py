"""Test configuration — use a separate test database to avoid polluting production data.

This conftest patches the database engine AFTER import to redirect all DB writes
to a temporary test database. The production database is never touched.
"""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

TEST_DB_URL = "sqlite+aiosqlite:////tmp/voxyflow_test.db"


@pytest.fixture(autouse=True, scope="session")
def _use_test_database():
    """Redirect the app's database engine to a test DB for the entire test session."""
    import app.database as db_module

    # Create a test engine and session factory
    test_engine = create_async_engine(TEST_DB_URL, echo=False)
    test_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    # Monkey-patch the module-level objects
    original_engine = db_module.engine
    original_session = db_module.async_session

    db_module.engine = test_engine
    db_module.async_session = test_session

    yield

    # Restore originals (probably not needed, but clean)
    db_module.engine = original_engine
    db_module.async_session = original_session

