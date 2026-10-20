"""The empty baseline migration applies cleanly to an empty database.

This is milestone 1's migration criterion in ARCHITECTURE.md §12: `alembic
upgrade head` from empty, and back down again, with nothing left behind.

Each test runs against its own throwaway database so a failure cannot leave the
development database half-migrated.
"""

import asyncio
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings

API_ROOT = Path(__file__).resolve().parents[2]
BASELINE = "0001_baseline"


@pytest.fixture
async def empty_database() -> str:
    """Create a scratch database, yield its URL, drop it afterwards."""
    url = make_url(settings.dsn)
    name = f"test_migrations_{uuid.uuid4().hex[:12]}"

    admin = create_async_engine(url.set(database="postgres").render_as_string(hide_password=False))
    try:
        async with admin.connect() as connection:
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.execute(text(f'CREATE DATABASE "{name}"'))

        yield url.set(database=name).render_as_string(hide_password=False)

        async with admin.connect() as connection:
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        await admin.dispose()


def alembic_config(url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config


async def run_alembic(config: Config, action, revision: str) -> None:
    """Run an Alembic command off the test's event loop.

    alembic/env.py calls asyncio.run(), which refuses to nest inside a running
    loop.  A worker thread has no loop, so the command runs exactly as it does
    from the command line.
    """
    await asyncio.to_thread(action, config, revision)


async def table_names(url: str) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            return {row[0] for row in rows}
    finally:
        await engine.dispose()


async def current_revision(url: str) -> str | None:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            return result.scalar_one_or_none()
    finally:
        await engine.dispose()


async def test_upgrade_head_applies_to_an_empty_database(empty_database: str) -> None:
    assert await table_names(empty_database) == set()

    await run_alembic(alembic_config(empty_database), command.upgrade, "head")

    assert await current_revision(empty_database) == BASELINE
    # The baseline creates nothing but Alembic's own bookkeeping table.
    assert await table_names(empty_database) == {"alembic_version"}


async def test_downgrade_to_base_is_clean(empty_database: str) -> None:
    config = alembic_config(empty_database)

    await run_alembic(config, command.upgrade, "head")
    await run_alembic(config, command.downgrade, "base")

    assert await current_revision(empty_database) is None


async def test_upgrade_is_idempotent(empty_database: str) -> None:
    config = alembic_config(empty_database)

    await run_alembic(config, command.upgrade, "head")
    await run_alembic(config, command.upgrade, "head")

    assert await current_revision(empty_database) == BASELINE


def test_baseline_is_the_only_revision_and_has_no_parent() -> None:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_config(settings.dsn))
    revisions = list(script.walk_revisions())

    assert [r.revision for r in revisions] == [BASELINE]
    assert revisions[0].down_revision is None
