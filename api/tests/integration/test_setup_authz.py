"""Nobody but an admin reaches the setup surface (ARCHITECTURE.md §5.2).

§5.2's first three rows give sessions, terms, assessment periods, classes,
subjects, user creation, teacher assignment, the grading scale, marks
obtainable, narrative sections and the comment bank to the **admin alone** —
every other column is a dash.

Two tests, doing different jobs:

A behavioural table that actually calls each endpoint as a head teacher, a
teacher and a parent, because a dependency that is present but wrong is still
a leak. The structural half — every route carries a gate, and every route
appears in one of these tables — is in `test_route_coverage.py`, which needs
the union of this table and the teacher one.
"""

import pytest
from httpx import AsyncClient

from app.config import settings
from app.models import UserRole
from tests.integration.routes import ANY_ID, call, ids_for

# Every admin setup endpoint of §7, with a body good enough to reach the
# handler. None of these should ever get that far as a non-admin.
SETUP_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/sessions", None),
    ("POST", "/sessions", {"name": "X", "starts_on": "2026-09-14", "ends_on": "2027-07-23"}),
    ("POST", f"/sessions/{ANY_ID}/current", None),
    ("GET", "/terms", None),
    (
        "POST",
        "/terms",
        {
            "academic_session_id": ANY_ID,
            "number": "first",
            "starts_on": "2026-09-14",
            "ends_on": "2026-12-11",
        },
    ),
    ("PATCH", f"/terms/{ANY_ID}", {"times_school_opened": 60}),
    ("POST", f"/terms/{ANY_ID}/current", None),
    ("GET", f"/terms/{ANY_ID}/assessment-periods", None),
    ("POST", f"/terms/{ANY_ID}/assessment-periods", {"half": "first_half"}),
    ("GET", f"/assessment-periods/{ANY_ID}/marks-obtainable", None),
    ("PUT", f"/assessment-periods/{ANY_ID}/marks-obtainable", {"mid_term_test": "40"}),
    ("GET", "/classes", None),
    ("POST", "/classes", {"name": "Primary 4", "level_order": 4}),
    ("GET", "/houses", None),
    ("POST", "/houses", {"name": "Blue"}),
    ("GET", "/subjects", None),
    ("POST", "/subjects", {"name": "Mathematics"}),
    ("PATCH", f"/subjects/{ANY_ID}", {"display_order": 1}),
    ("GET", f"/classes/{ANY_ID}/subjects", None),
    ("PUT", f"/classes/{ANY_ID}/subjects", {"subject_ids": []}),
    ("PUT", f"/class-subjects/{ANY_ID}/teacher", {"teacher_user_id": ANY_ID}),
    ("PUT", f"/classes/{ANY_ID}/class-teacher", {"teacher_user_id": ANY_ID}),
    ("GET", "/pupils", None),
    (
        "POST",
        "/pupils",
        {"admission_number": "A/1", "first_name": "Ada", "last_name": "Okafor"},
    ),
    ("PUT", f"/pupils/{ANY_ID}/enrollment", {"class_id": ANY_ID}),
    ("GET", "/users", None),
    ("POST", "/users", {"role": "teacher", "full_name": "T", "email": "t@sshms.test"}),
    ("POST", f"/users/{ANY_ID}/reset-password", None),
    ("GET", f"/guardians/{ANY_ID}/children", None),
    (
        "POST",
        f"/guardians/{ANY_ID}/children",
        {"children": [{"pupil_id": ANY_ID}]},
    ),
    ("GET", "/grading-scales", None),
    (
        "POST",
        "/grading-scales",
        {
            "name": "S",
            "effective_from": "2026-09-14",
            "bands": [{"letter": "A", "remark": "Good", "min_score": "0", "max_score": "100"}],
        },
    ),
    ("POST", f"/grading-scales/{ANY_ID}/activate", None),
    ("GET", "/narrative-sections", None),
    (
        "PUT",
        "/narrative-sections",
        {"sections": [{"code": "B", "label": "Work", "display_order": 0}]},
    ),
    ("GET", f"/classes/{ANY_ID}/narrative-assignments", None),
    (
        "PUT",
        f"/classes/{ANY_ID}/narrative-assignments",
        {"assignments": [{"section_id": ANY_ID, "teacher_user_id": None}]},
    ),
    ("GET", "/comment-bank", None),
    ("POST", "/comment-bank", {"scope": "class_teacher", "text": "Steady."}),
    ("GET", f"/setup-checklist?term_id={ANY_ID}", None),
]

NON_ADMIN_ROLES = [UserRole.HEAD_TEACHER, UserRole.TEACHER, UserRole.PARENT]


# ---------------------------------------------------------------------------
# The structural guard
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The behavioural table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", SETUP_ENDPOINTS, ids=ids_for)
@pytest.mark.parametrize("role", NON_ADMIN_ROLES, ids=lambda role: role.value)
async def test_no_other_role_reaches_the_setup_surface(
    client: AsyncClient, make_user, headers_for, case, role: UserRole
) -> None:
    """Every dash in §5.2's first three rows, asserted against a live route."""
    user = await make_user(role)
    headers = await headers_for(user)

    response = await call(client, case, headers)

    assert response.status_code == 403, f"{case[0]} {case[1]} as {role.value}"
    assert response.json()["detail"] == "Your role does not permit this action."


@pytest.mark.parametrize("case", SETUP_ENDPOINTS, ids=ids_for)
async def test_the_setup_surface_requires_authentication(client: AsyncClient, case) -> None:
    response = await call(client, case, None)

    assert response.status_code == 401


async def test_an_admin_owing_a_password_change_is_stopped_first(
    client: AsyncClient, make_user, login
) -> None:
    """§5.1's temporary password works once. The gate runs before the
    capability check, so a new admin cannot set anything up until they have
    replaced it.
    """
    admin = await make_user(UserRole.ADMIN, must_change_password=True)
    token = (await login(admin.email)).json()["access_token"]

    response = await client.get(
        f"{settings.api_v1_prefix}/sessions", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 409
    assert "change your password" in response.json()["detail"]


async def test_a_deactivated_admin_is_refused(client: AsyncClient, make_user, headers_for) -> None:
    admin = await make_user(UserRole.ADMIN)
    headers = await headers_for(admin)
    admin.is_active = False
    from app.db import SessionLocal

    async with SessionLocal() as db:
        await db.merge(admin)
        await db.commit()

    response = await client.get(f"{settings.api_v1_prefix}/sessions", headers=headers)

    assert response.status_code == 401
