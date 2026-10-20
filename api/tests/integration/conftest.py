"""Fixtures for tests that touch the database.

Real PostgreSQL 16, never SQLite (ARCHITECTURE.md §10): generated columns,
enums, citext and triggers all behave differently, and a suite that passes
against a database you do not run is worth nothing.

State is reset by truncating between tests rather than by wrapping each test
in a rolled-back transaction. The auth rules commit deliberately — a failed
login must persist its attempt counter even though the request fails — and a
harness that swallowed commits would hide exactly that.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal, engine
from app.main import app
from app.models import School, User, UserRole
from tests.conftest import TEST_PASSWORD

# Everything tenant-scoped references schools, directly or through one hop,
# and TRUNCATE ... CASCADE follows those references transitively. Naming the
# root keeps this correct as tables are added, and is far faster than
# truncating thirty tables by name before every test.
TABLES = ("schools",)


@pytest.fixture(autouse=True)
async def clean_database() -> AsyncIterator[None]:
    """Empty the auth tables before each test."""
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as db_session:
        yield db_session


@pytest.fixture
async def school(session: AsyncSession) -> School:
    record = School(name="Self-Starters House Montessori School", short_name="SSHMS")
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


@pytest.fixture
async def make_user(session: AsyncSession, school: School, password_hash: str):
    """Factory for a user of any role."""

    async def _make(
        role: UserRole = UserRole.TEACHER,
        *,
        email: str | None = None,
        phone: str | None = None,
        must_change_password: bool = False,
        is_active: bool = True,
        full_name: str = "Test Person",
    ) -> User:
        if email is None and phone is None:
            email = f"{role.value}-{uuid.uuid4().hex[:8]}@sshms.test"

        user = User(
            school_id=school.id,
            role=role,
            email=email,
            phone=phone,
            full_name=full_name,
            password_hash=password_hash,
            must_change_password=must_change_password,
            is_active=is_active,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    return _make


@pytest.fixture
async def users(make_user) -> dict[UserRole, User]:
    """One user per role — the §5.2 cast, for the four-role assertions."""
    return {role: await make_user(role) for role in UserRole}


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An HTTP client bound directly to the ASGI app.

    No lifespan manager is needed: app.db builds the engine at import time, so
    the database is reachable without starting the application's lifespan.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://api.test") as http_client:
        yield http_client


@pytest.fixture
async def login(client: AsyncClient):
    """Sign a user in, returning the raw response."""

    async def _login(identifier: str, password: str = TEST_PASSWORD):
        return await client.post(
            "/api/v1/auth/login",
            json={"identifier": identifier, "password": password},
        )

    return _login
