"""The migration chain applies cleanly to an empty database.

Written to be revision-agnostic: every milestone adds a revision, and these
tests must not need editing each time. Where a specific revision matters —
milestone 1's criterion that the baseline applies on its own — it is named
explicitly and says why.

Each test runs against its own throwaway database so a failure cannot leave
the development database half-migrated.
"""

import asyncio
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.models import Base

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
    loop. A worker thread has no loop, so the command runs exactly as it does
    from the command line.
    """
    await asyncio.to_thread(action, config, revision)


def head_revision() -> str:
    script = ScriptDirectory.from_config(alembic_config(settings.dsn))
    return script.get_current_head()


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

    assert await current_revision(empty_database) == head_revision()


async def test_the_baseline_applies_on_its_own(empty_database: str) -> None:
    """Milestone 1's criterion: the empty first revision applies to an empty
    database and creates nothing but Alembic's own bookkeeping."""
    await run_alembic(alembic_config(empty_database), command.upgrade, BASELINE)

    assert await current_revision(empty_database) == BASELINE
    assert await table_names(empty_database) == {"alembic_version"}


async def test_every_table_in_the_models_exists_after_upgrade(empty_database: str) -> None:
    await run_alembic(alembic_config(empty_database), command.upgrade, "head")

    tables = await table_names(empty_database)

    assert set(Base.metadata.tables) <= tables


async def test_the_models_and_the_migrations_agree(empty_database: str) -> None:
    """No pending schema changes after upgrading to head.

    This is CLAUDE.md rule 3 as a test: edit a model without generating the
    migration and this fails, rather than the drift being found in production.
    """
    await run_alembic(alembic_config(empty_database), command.upgrade, "head")

    engine = create_async_engine(empty_database)
    try:
        async with engine.connect() as connection:
            differences = await connection.run_sync(
                lambda sync_connection: compare_metadata(
                    MigrationContext.configure(
                        sync_connection,
                        opts={"compare_type": True, "compare_server_default": True},
                    ),
                    Base.metadata,
                )
            )
    finally:
        await engine.dispose()

    assert differences == [], f"models drifted from migrations: {differences}"


async def test_downgrade_to_base_is_clean(empty_database: str) -> None:
    config = alembic_config(empty_database)

    await run_alembic(config, command.upgrade, "head")
    await run_alembic(config, command.downgrade, "base")

    assert await current_revision(empty_database) is None
    assert await table_names(empty_database) == {"alembic_version"}


async def test_a_full_down_and_up_cycle_works(empty_database: str) -> None:
    """Catches state a downgrade forgets to remove — a Postgres enum type
    survives DROP TABLE, and a re-upgrade then fails with "already exists"."""
    config = alembic_config(empty_database)

    await run_alembic(config, command.upgrade, "head")
    await run_alembic(config, command.downgrade, "base")
    await run_alembic(config, command.upgrade, "head")

    assert await current_revision(empty_database) == head_revision()


async def test_upgrade_is_idempotent(empty_database: str) -> None:
    config = alembic_config(empty_database)

    await run_alembic(config, command.upgrade, "head")
    await run_alembic(config, command.upgrade, "head")

    assert await current_revision(empty_database) == head_revision()


def test_the_chain_is_linear_and_rooted_at_the_baseline() -> None:
    """One root, one head, no branches.

    Alembic supports branching; this project has no use for it, and a
    stray branch means two developers generated a revision from the same
    parent and one of them will be silently skipped.
    """
    script = ScriptDirectory.from_config(alembic_config(settings.dsn))
    revisions = list(script.walk_revisions())

    roots = [r for r in revisions if r.down_revision is None]
    assert len(roots) == 1
    assert roots[0].revision == BASELINE
    assert len(script.get_heads()) == 1

    for revision in revisions:
        assert not isinstance(revision.down_revision, tuple), (
            f"{revision.revision} is a merge point"
        )
