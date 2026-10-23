"""Driving Alembic from the test suite.

Shared because two callers need it: the migration tests, which apply the chain
to a throwaway database, and the integration fixtures, which bring the suite's
own database up to head before the first test runs.
"""

import asyncio
from collections.abc import Callable
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

API_ROOT = Path(__file__).resolve().parents[1]


def alembic_config(url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config


async def run_alembic(config: Config, action: Callable[..., None], revision: str) -> None:
    """Run an Alembic command off the test's event loop.

    alembic/env.py calls asyncio.run(), which refuses to nest inside a running
    loop. A worker thread has no loop, so the command runs exactly as it does
    from the command line.
    """
    await asyncio.to_thread(action, config, revision)


def head_revision(url: str) -> str:
    return ScriptDirectory.from_config(alembic_config(url)).get_current_head()
