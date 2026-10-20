"""Shared test fixtures.

Tests run against a real PostgreSQL 16, never SQLite (ARCHITECTURE.md §10):
generated columns, enums, citext and triggers all behave differently, and a
suite that passes against a database you do not run is worth nothing.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An HTTP client bound directly to the ASGI app.

    No lifespan manager is needed: app.db builds the engine at import time, so
    the database is reachable without starting the application's lifespan.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
