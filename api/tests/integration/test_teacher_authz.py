"""Nobody but the right teacher reaches a class's work (§5.2, §6 R14).

§5.2's four teaching rows — enter scores, write the narrative (both kinds),
record attendance and growth, submit — read teacher ✅ **own class** or **own
class-subjects**, with a dash in every other column. Two things have to hold,
and they fail differently:

- An admin, a head teacher or a parent is refused outright — a **403**, from
  the capability gate. There is nothing to hide: nobody of that role enters
  scores, whatever exists behind the endpoint.
- Another teacher's sheet is **404**, from the scope filter. A 403 there would
  confirm the sheet exists, which is itself a leak.

The head teacher's dash is the surprising one and it is deliberate: §5.2 gives
them review and remarks, not entry. Correcting a score after approval is the
admin's `PATCH /entries/{id}` (milestone 10), audited and with a reason.

The phrase bank is the one exception in this file, and it is in its own table:
every member of staff reads it and no parent does (docs/DECISIONS.md D55).
"""

import pytest
from httpx import AsyncClient

from app.config import settings
from app.models import UserRole
from tests.integration.routes import ANY_ID, call, ids_for

API = settings.api_v1_prefix

# §7's teacher block, as built in milestone 6. Bodies are good enough to reach
# the handler; none of these callers should ever get that far.
ENTRY_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", f"/my/assignments?term_id={ANY_ID}", None),
    ("GET", f"/class-subjects/{ANY_ID}/entries?assessment_period_id={ANY_ID}", None),
    (
        "PUT",
        f"/class-subjects/{ANY_ID}/entries",
        {
            "assessment_period_id": ANY_ID,
            "rows": [{"pupil_id": ANY_ID, "ca_test_1": "5"}],
        },
    ),
]

# §8.2's narrative screen, §4.7's attendance and growth, and the class
# teacher's comment. All teacher-only, all per class.
CLASSWORK_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", f"/classes/{ANY_ID}/narrative?term_id={ANY_ID}", None),
    ("GET", f"/pupils/{ANY_ID}/narrative?term_id={ANY_ID}", None),
    (
        "PUT",
        f"/pupils/{ANY_ID}/narrative?term_id={ANY_ID}",
        {"passages": [{"section_id": ANY_ID, "body": "Steady progress."}]},
    ),
    ("GET", f"/classes/{ANY_ID}/attendance?term_id={ANY_ID}", None),
    (
        "PUT",
        f"/classes/{ANY_ID}/attendance?term_id={ANY_ID}",
        {"rows": [{"pupil_id": ANY_ID, "times_present": 50, "times_absent": 10}]},
    ),
    ("GET", f"/classes/{ANY_ID}/growth?term_id={ANY_ID}", None),
    (
        "PUT",
        f"/classes/{ANY_ID}/growth?term_id={ANY_ID}",
        {"rows": [{"pupil_id": ANY_ID, "height_start_m": "1.2"}]},
    ),
    ("GET", f"/classes/{ANY_ID}/comments?term_id={ANY_ID}", None),
    (
        "PUT",
        f"/classes/{ANY_ID}/comments?term_id={ANY_ID}",
        {"rows": [{"pupil_id": ANY_ID, "comment": "A good term."}]},
    ),
]

# §8.3's progress page and R10's gate.
SUBMISSION_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", f"/classes/{ANY_ID}/progress?term_id={ANY_ID}", None),
    ("POST", f"/classes/{ANY_ID}/submit?term_id={ANY_ID}", None),
]

TEACHER_ONLY_ENDPOINTS = ENTRY_ENDPOINTS + CLASSWORK_ENDPOINTS + SUBMISSION_ENDPOINTS

# Read by everyone who writes about a pupil; never by a parent (D55).
STAFF_ENDPOINTS: list[tuple[str, str, dict | None]] = [
    ("GET", "/phrases", None),
    ("GET", "/phrases?scope=B", None),
]

# Every column of §5.2's teaching rows that holds a dash.
ROLES_WITHOUT_ENTRY = [UserRole.ADMIN, UserRole.HEAD_TEACHER, UserRole.PARENT]


@pytest.mark.parametrize("case", TEACHER_ONLY_ENDPOINTS, ids=ids_for)
@pytest.mark.parametrize("role", ROLES_WITHOUT_ENTRY, ids=lambda role: role.value)
async def test_only_a_teacher_reaches_the_entry_surface(
    client: AsyncClient, make_user, headers_for, case, role: UserRole
) -> None:
    user = await make_user(role)
    headers = await headers_for(user)

    response = await call(client, case, headers)

    assert response.status_code == 403, f"{case[0]} {case[1]} as {role.value}"
    assert response.json()["detail"] == "Your role does not permit this action."


@pytest.mark.parametrize("case", TEACHER_ONLY_ENDPOINTS + STAFF_ENDPOINTS, ids=ids_for)
async def test_the_entry_surface_requires_authentication(client: AsyncClient, case) -> None:
    response = await call(client, case, None)

    assert response.status_code == 401


@pytest.mark.parametrize("case", TEACHER_ONLY_ENDPOINTS, ids=ids_for)
async def test_a_teacher_owing_a_password_change_is_stopped_first(
    client: AsyncClient, make_user, login, case
) -> None:
    """§5.1's temporary password works once, and the gate runs first."""
    teacher = await make_user(UserRole.TEACHER, must_change_password=True)
    token = (await login(teacher.email)).json()["access_token"]

    response = await call(client, case, {"Authorization": f"Bearer {token}"})

    assert response.status_code == 409
    assert "change your password" in response.json()["detail"]


async def test_a_deactivated_teacher_is_refused(
    client: AsyncClient, session, make_user, login
) -> None:
    """A teacher who has left the school keeps neither sight nor write.

    Deactivated *after* signing in, so the live access token is the thing
    being tested: §5.1 checks the account on every request rather than
    trusting a token issued half an hour ago.
    """
    teacher = await make_user(UserRole.TEACHER)
    token = (await login(teacher.email)).json()["access_token"]

    teacher.is_active = False
    await session.commit()

    response = await client.get(
        f"{API}/my/assignments",
        params={"term_id": ANY_ID},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# The phrase bank: staff yes, parent no (D55)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", STAFF_ENDPOINTS, ids=ids_for)
async def test_a_parent_never_reaches_the_phrase_bank(
    client: AsyncClient, make_user, headers_for, case
) -> None:
    """The phrases are staff drafting material. A parent reads the finished
    passage on a published report and nothing else."""
    parent = await make_user(UserRole.PARENT)
    headers = await headers_for(parent)

    response = await call(client, case, headers)

    assert response.status_code == 403


@pytest.mark.parametrize("case", STAFF_ENDPOINTS, ids=ids_for)
@pytest.mark.parametrize(
    "role",
    [UserRole.ADMIN, UserRole.HEAD_TEACHER, UserRole.TEACHER],
    ids=lambda role: role.value,
)
async def test_every_member_of_staff_reaches_the_phrase_bank(
    client: AsyncClient, make_user, headers_for, case, role: UserRole
) -> None:
    """§4.6 calls the bank core, not optional. A head teacher has their own
    'head_teacher'-scoped phrases for the remark (milestone 9)."""
    user = await make_user(role)
    headers = await headers_for(user)

    response = await call(client, case, headers)

    assert response.status_code == 200, f"{case[0]} {case[1]} as {role.value}"


# ---------------------------------------------------------------------------
# The scope half: another teacher's sheet
# ---------------------------------------------------------------------------


async def test_another_teachers_sheet_is_not_found(client: AsyncClient, headers_for, world) -> None:
    """Teacher B teaches 5B Mathematics. Teacher A does not, and is class
    teacher of 4A — which §5.2 says grants nothing here."""
    headers = await headers_for(world.teacher_a)

    response = await client.get(
        f"{API}/class-subjects/{world.maths_5b.id}/entries",
        params={"assessment_period_id": ANY_ID},
        headers=headers,
    )

    assert response.status_code == 404


async def test_a_class_teacher_cannot_write_a_colleagues_subject(
    client: AsyncClient, headers_for, world
) -> None:
    """The union case §5.2 names: being class teacher of 4A does not grant
    4A Computer, which is the specialist's."""
    headers = await headers_for(world.teacher_a)

    response = await client.put(
        f"{API}/class-subjects/{world.computer_4a.id}/entries",
        json={
            "assessment_period_id": ANY_ID,
            "rows": [{"pupil_id": str(world.pupils["ada"].id), "ca_test_1": "5"}],
        },
        headers=headers,
    )

    assert response.status_code == 404


async def test_a_teacher_sees_no_other_schools_sheets(
    client: AsyncClient, session, headers_for, world, password_hash
) -> None:
    """§2.2: every query is filtered by school_id, not only by assignment."""
    from app.models import School, User

    other_school = School(name="Another School", short_name="AS")
    session.add(other_school)
    await session.flush()
    intruder = User(
        school_id=other_school.id,
        role=UserRole.TEACHER,
        full_name="Elsewhere",
        email="elsewhere@other.test",
        password_hash=password_hash,
        must_change_password=False,
    )
    session.add(intruder)
    await session.commit()

    headers = await headers_for(intruder)

    response = await client.get(
        f"{API}/class-subjects/{world.maths_4a.id}/entries",
        params={"assessment_period_id": ANY_ID},
        headers=headers,
    )

    assert response.status_code == 404
