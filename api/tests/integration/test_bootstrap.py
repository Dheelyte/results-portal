"""Creating the first school and admin (app.bootstrap).

§5.1 says accounts are admin-created and never self-registered, which leaves
no way to create the first one. This command is that way, and it is a command
rather than an endpoint because an unauthenticated "create an admin" route is
a back door however carefully guarded.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.bootstrap import bootstrap
from app.models import AuditAction, AuditLog, School, User, UserRole

ARGS = {
    "school_name": "Self-Starters House Montessori School",
    "short_name": "SSHMS",
    "admin_name": "A Head",
    "admin_email": "admin@sshms.test",
    "admin_phone": None,
}


async def test_it_creates_a_school_and_an_admin(session) -> None:
    password = await bootstrap(**ARGS)

    school = await session.scalar(select(School))
    admin = await session.scalar(select(User))

    assert school.short_name == "SSHMS"
    assert admin.role is UserRole.ADMIN
    assert admin.school_id == school.id
    assert len(password) >= 8


async def test_the_admin_must_change_the_temporary_password(session) -> None:
    await bootstrap(**ARGS)

    admin = await session.scalar(select(User))

    assert admin.must_change_password is True


async def test_the_temporary_password_is_not_stored_in_readable_form(session) -> None:
    password = await bootstrap(**ARGS)

    admin = await session.scalar(select(User))

    assert password not in admin.password_hash
    assert admin.password_hash.startswith("$argon2id$")


async def test_the_generated_password_actually_works(client: AsyncClient) -> None:
    password = await bootstrap(**ARGS)

    response = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "admin@sshms.test", "password": password},
    )

    assert response.status_code == 200
    assert response.json()["user"]["must_change_password"] is True


async def test_it_refuses_to_run_twice(session) -> None:
    """Otherwise it is an unauthenticated route to a second admin account."""
    await bootstrap(**ARGS)

    with pytest.raises(SystemExit, match="already exists"):
        await bootstrap(**{**ARGS, "admin_email": "another@sshms.test"})

    assert await session.scalar(select(func.count()).select_from(User)) == 1


async def test_an_admin_with_no_identifier_is_refused() -> None:
    """users has a CHECK that email or phone must be present; fail with a
    readable message rather than an IntegrityError."""
    with pytest.raises(SystemExit, match="admin-email"):
        await bootstrap(**{**ARGS, "admin_email": None, "admin_phone": None})


async def test_an_admin_may_be_created_with_only_a_phone_number(session) -> None:
    await bootstrap(**{**ARGS, "admin_email": None, "admin_phone": "+2348012345678"})

    admin = await session.scalar(select(User))

    assert admin.email is None
    assert admin.phone == "+2348012345678"


async def test_creating_the_school_and_admin_is_audited(session) -> None:
    await bootstrap(**ARGS)

    actions = set((await session.execute(select(AuditLog.action))).scalars().all())

    assert AuditAction.SCHOOL_CREATED in actions
    assert AuditAction.USER_CREATED in actions


async def test_the_audit_trail_never_carries_the_temporary_password(session) -> None:
    password = await bootstrap(**ARGS)

    rows = (await session.execute(select(AuditLog))).scalars().all()
    blob = " ".join(f"{r.before} {r.after}" for r in rows)

    assert password not in blob
    assert "$argon2" not in blob
