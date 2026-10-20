"""Alembic environment, async throughout.

The database URL is taken from app.config.settings rather than alembic.ini, so
no credential lives in the repository (ARCHITECTURE.md §11).
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings

# Milestone 1 defines no tables, so Base.metadata is empty and --autogenerate
# correctly produces an empty revision.  Milestone 3 populates app.models and
# this import starts seeing the real schema with no change here.
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# settings supplies the default, but a caller that has already set a URL wins:
# the test suite points each run at a throwaway database, and a one-off
# migration against a restored backup needs the same hook.  Overriding
# unconditionally would silently send both at the development database.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", settings.dsn)

target_metadata = Base.metadata

# compare_type and compare_server_default are on from the first revision so
# that milestone 3's autogenerate notices a numeric(5,2) widening or a changed
# DEFAULT instead of silently skipping it.
_COMPARE_OPTIONS = {
    "compare_type": True,
    "compare_server_default": True,
}


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting — `alembic upgrade head --sql`."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url", settings.dsn),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_COMPARE_OPTIONS,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, **_COMPARE_OPTIONS)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
