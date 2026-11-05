"""Who may publish, who may correct, who may read the log, and who may read a
child's report (§5.2).

Three different shapes in one file, because they are three rows of the same
table and reading them together is how you see that they differ:

- **Publish, withhold, release, edit after publication** — the admin alone.
  Not the head teacher's: §1.6 keeps approve and publish as two steps held by
  two people, so the role that approved a class cannot also release it.
- **The audit log** — admin and head teacher. §5.2 marks the head teacher
  "read-only", and in a GET-only resource that is the same rows; what makes it
  read-only is that nothing here writes and `services/audit.py` is the only
  writer in the codebase.
- **A child's report** — the parent alone. Staff read a card through the
  review and publication screens, which carry more than a parent sees.
"""

import pytest
from httpx import AsyncClient

from app.models import UserRole
from tests.integration.routes import ANY_ID, call, ids_for

PUBLICATION_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", f"/classes/{ANY_ID}/publication?term_id={ANY_ID}", None),
    (
        "POST",
        f"/classes/{ANY_ID}/publish?term_id={ANY_ID}",
        {"withhold_pupil_ids": [], "reason": None},
    ),
    ("POST", f"/reports/{ANY_ID}/release", None),
    ("POST", f"/reports/{ANY_ID}/withhold", {"reason": "Fees outstanding."}),
    ("PATCH", f"/entries/{ANY_ID}", {"reason": "Transposed digits.", "ca_test_1": "7"}),
    ("GET", f"/pupils/{ANY_ID}/entries?term_id={ANY_ID}", None),
    # §9's card, for the school's own printing (docs/DECISIONS.md D83).
    ("GET", f"/pupils/{ANY_ID}/card?term_id={ANY_ID}&half=first_half", None),
]

AUDIT_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/audit", None),
    ("GET", f"/audit?entity_type=term_report&entity_id={ANY_ID}", None),
]

PARENT_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/my/children", None),
    ("GET", f"/my/children/{ANY_ID}/reports", None),
    ("GET", f"/my/children/{ANY_ID}/reports/{ANY_ID}", None),
    ("GET", f"/my/children/{ANY_ID}/reports/{ANY_ID}/pdf?half=first_half", None),
]

ROLES_WITHOUT_PUBLICATION = [UserRole.HEAD_TEACHER, UserRole.TEACHER, UserRole.PARENT]
ROLES_WITHOUT_AUDIT = [UserRole.TEACHER, UserRole.PARENT]
ROLES_THAT_ARE_NOT_PARENTS = [UserRole.ADMIN, UserRole.HEAD_TEACHER, UserRole.TEACHER]


@pytest.mark.parametrize("case", PUBLICATION_ENDPOINTS, ids=ids_for)
@pytest.mark.parametrize("role", ROLES_WITHOUT_PUBLICATION, ids=lambda role: role.value)
async def test_only_the_admin_publishes(
    client: AsyncClient, make_user, headers_for, case, role: UserRole
) -> None:
    """The head teacher's dash is the one worth noticing: they approved the
    class, and releasing it is somebody else's decision (§1.6)."""
    user = await make_user(role)
    headers = await headers_for(user)

    response = await call(client, case, headers)

    assert response.status_code == 403, f"{case[0]} {case[1]} as {role.value}"
    assert response.json()["detail"] == "Your role does not permit this action."


@pytest.mark.parametrize("case", AUDIT_ENDPOINTS, ids=ids_for)
@pytest.mark.parametrize("role", ROLES_WITHOUT_AUDIT, ids=lambda role: role.value)
async def test_no_teacher_or_parent_reads_the_audit_log(
    client: AsyncClient, make_user, headers_for, case, role: UserRole
) -> None:
    """The log carries before/after values — R13's edits record the actual
    scores — so its audience is the two roles who already see every card."""
    user = await make_user(role)
    headers = await headers_for(user)

    response = await call(client, case, headers)

    assert response.status_code == 403


@pytest.mark.parametrize("case", AUDIT_ENDPOINTS, ids=ids_for)
@pytest.mark.parametrize(
    "role", [UserRole.ADMIN, UserRole.HEAD_TEACHER], ids=lambda role: role.value
)
async def test_the_admin_and_the_head_teacher_read_the_audit_log(
    client: AsyncClient, make_user, headers_for, case, role: UserRole
) -> None:
    user = await make_user(role)
    headers = await headers_for(user)

    response = await call(client, case, headers)

    assert response.status_code == 200, f"{case[0]} {case[1]} as {role.value}"


@pytest.mark.parametrize("case", PARENT_ENDPOINTS, ids=ids_for)
@pytest.mark.parametrize("role", ROLES_THAT_ARE_NOT_PARENTS, ids=lambda role: role.value)
async def test_only_a_parent_reads_a_childs_report(
    client: AsyncClient, make_user, headers_for, case, role: UserRole
) -> None:
    """Staff read a card through review and publication, which carry more than
    a parent sees — and a member of staff is not anybody's guardian."""
    user = await make_user(role)
    headers = await headers_for(user)

    response = await call(client, case, headers)

    assert response.status_code == 403


@pytest.mark.parametrize(
    "case", PUBLICATION_ENDPOINTS + AUDIT_ENDPOINTS + PARENT_ENDPOINTS, ids=ids_for
)
async def test_the_whole_surface_requires_authentication(client: AsyncClient, case) -> None:
    response = await call(client, case, None)

    assert response.status_code == 401


@pytest.mark.parametrize("case", PUBLICATION_ENDPOINTS, ids=ids_for)
async def test_an_admin_owing_a_password_change_is_stopped_first(
    client: AsyncClient, make_user, login, case
) -> None:
    admin = await make_user(UserRole.ADMIN, must_change_password=True)
    token = (await login(admin.email)).json()["access_token"]

    response = await call(client, case, {"Authorization": f"Bearer {token}"})

    assert response.status_code == 409
    assert "change your password" in response.json()["detail"]


async def test_a_parent_sees_none_of_another_familys_children(
    client: AsyncClient, headers_for, world
) -> None:
    """The single most important filter in the system (§5.2).

    `other_parent` has no children at all. Ada exists, and is somebody's.
    """
    headers = await headers_for(world.other_parent)

    listing = await client.get("/api/v1/my/children", headers=headers)
    assert listing.status_code == 200
    assert listing.json() == []

    direct = await client.get(
        f"/api/v1/my/children/{world.pupils['ada'].id}/reports", headers=headers
    )
    assert direct.status_code == 404


async def test_a_parent_sees_their_own_children(client: AsyncClient, headers_for, world) -> None:
    """§10: "a parent with two children in different classes"."""
    headers = await headers_for(world.parent)

    response = await client.get("/api/v1/my/children", headers=headers)

    assert response.status_code == 200
    assert {child["first_name"] for child in response.json()} == {"Ada", "Chidi"}
