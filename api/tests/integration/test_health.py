"""The liveness and readiness probes of ARCHITECTURE.md §11.

Requires a reachable PostgreSQL; see tests/conftest.py.
"""

import pytest
from httpx import AsyncClient

from app import db
from app.config import settings


async def test_healthz_is_ok(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_healthz_does_not_touch_the_database(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Liveness must stay green while the database is down, or an orchestrator
    restarts a perfectly healthy process every time Postgres blinks."""

    async def unreachable() -> bool:  # pragma: no cover - must never be called
        raise AssertionError("/healthz queried the database")

    monkeypatch.setattr(db, "check_database", unreachable)

    assert (await client.get("/healthz")).status_code == 200


async def test_readyz_is_ready_when_the_database_is_reachable(client: AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


async def test_readyz_is_503_when_the_database_is_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.routers import health

    async def unreachable() -> bool:
        return False

    monkeypatch.setattr(health, "check_database", unreachable)

    response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unreachable"}


async def test_readyz_failure_body_leaks_no_connection_detail(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A readiness endpoint is normally unauthenticated.  Its failure body must
    name no host, user, password or driver (docs/DECISIONS.md, D9)."""
    from app.routers import health

    async def unreachable() -> bool:
        return False

    monkeypatch.setattr(health, "check_database", unreachable)

    body = (await client.get("/readyz")).text.lower()

    for fragment in ("asyncpg", "postgres", "portal", "5432", "password", "sqlalchemy"):
        assert fragment not in body

    for fragment in settings.dsn.replace("//", "/").replace("@", "/").split("/"):
        if fragment:
            assert fragment.lower() not in body


async def test_check_database_swallows_the_driver_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """check_database returns False rather than raising, so no driver message
    can reach a response through an unhandled exception.

    AsyncEngine.connect is slot-protected, so the whole engine is swapped.
    """

    class FailingConnection:
        async def __aenter__(self):
            raise OSError("connection to server at 10.0.0.1:5432 failed: password authentication")

        async def __aexit__(self, *exc):  # pragma: no cover - never reached
            return False

    class FailingEngine:
        def connect(self) -> FailingConnection:
            return FailingConnection()

    monkeypatch.setattr(db, "engine", FailingEngine())

    assert await db.check_database() is False


async def test_openapi_is_served_outside_production(client: AsyncClient) -> None:
    assert (await client.get("/openapi.json")).status_code == 200
