"""Nobody but an admin reaches the setup surface (ARCHITECTURE.md §5.2).

§5.2's first three rows give sessions, terms, assessment periods, classes,
subjects, user creation, teacher assignment, the grading scale, marks
obtainable, narrative sections and the comment bank to the **admin alone** —
every other column is a dash.

Two tests, doing different jobs:

- A structural one that walks the mounted routes and fails if a setup
  endpoint is mounted without a capability gate. It cannot go stale: a new
  endpoint added in milestone 6 without a gate fails it the day it lands.
- A behavioural table that actually calls each endpoint as a head teacher, a
  teacher and a parent, because a dependency that is present but wrong is
  still a leak.
"""

import uuid

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient

from app.config import settings
from app.main import app
from app.models import UserRole

ANY_ID = str(uuid.uuid4())

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


def ids_for(case: tuple[str, str, dict | None]) -> str:
    return f"{case[0]} {case[1].split('?')[0]}"


async def call(client: AsyncClient, case, headers: dict[str, str] | None):
    method, path, body = case
    return await client.request(
        method, f"{settings.api_v1_prefix}{path}", headers=headers, json=body
    )


# ---------------------------------------------------------------------------
# The structural guard
# ---------------------------------------------------------------------------


def capability_gated(route: APIRoute) -> bool:
    """Whether a capability dependency guards this route.

    Looks for the closure `authz.dependencies.requires` returns, anywhere in
    the route's dependency tree.
    """
    seen = [route.dependant]
    while seen:
        dependant = seen.pop()
        call_target = getattr(dependant, "call", None)
        qualname = getattr(call_target, "__qualname__", "")
        if qualname.startswith("requires.") and qualname.endswith("guard"):
            return True
        seen.extend(dependant.dependencies)
    return False


def mounted_routes(routes: object = None, prefix: str = "") -> list[tuple[str, APIRoute]]:
    """Every API route with its full path.

    `app.routes` holds `_IncludedRouter` wrappers rather than the routes
    themselves in this FastAPI version, and the mount prefix lives on the
    wrapper — so the path has to be reassembled while descending.
    """
    found: list[tuple[str, APIRoute]] = []
    for item in app.routes if routes is None else routes:
        if isinstance(item, APIRoute):
            found.append((prefix + item.path, item))
        elif hasattr(item, "original_router"):
            context = getattr(item, "include_context", None)
            found.extend(
                mounted_routes(
                    item.original_router.routes,
                    prefix + (getattr(context, "prefix", "") or ""),
                )
            )
    return found


def setup_routes() -> list[tuple[str, APIRoute]]:
    """Every /api/v1 route that is not an authentication route.

    The auth routes are deliberately open — a login endpoint that required
    being logged in would be a closed system.
    """
    return [
        (path, route)
        for path, route in mounted_routes()
        if path.startswith(settings.api_v1_prefix)
        and not path.startswith(f"{settings.api_v1_prefix}/auth")
    ]


def test_there_are_routes_to_check() -> None:
    """Guards against the scan passing because it found nothing."""
    assert len(setup_routes()) >= len(SETUP_ENDPOINTS)


@pytest.mark.parametrize(
    "case", setup_routes(), ids=lambda case: f"{sorted(case[1].methods)[0]} {case[0]}"
)
def test_every_setup_route_declares_a_capability(case: tuple[str, APIRoute]) -> None:
    path, route = case

    assert capability_gated(route), (
        f"{path} is mounted without a capability gate. Declare one of "
        "authz.dependencies' admin annotations in the signature (§5.2)."
    )


def test_the_endpoint_table_covers_every_mounted_route() -> None:
    """If an endpoint is added without a row above, the 403 table would
    quietly stop covering it."""

    def normalise(path: str) -> str:
        parts = path.removeprefix(settings.api_v1_prefix).lstrip("/").split("?")[0].split("/")
        return "/" + "/".join(
            "{id}" if part.startswith("{") or part == ANY_ID else part for part in parts
        )

    mounted = {
        (method, normalise(path))
        for path, route in setup_routes()
        for method in route.methods
        if method != "HEAD"
    }
    tabled = {(method, normalise(path)) for method, path, _ in SETUP_ENDPOINTS}

    assert mounted - tabled == set()


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
