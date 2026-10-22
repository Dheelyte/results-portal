"""Classes, houses, subjects, offerings and teachers over HTTP
(ARCHITECTURE.md §4.3, R7).

R7 is the rule under most of this file: a subject with `is_group = true` is a
heading on the card and carries no scores, so it can never be offered to a
class. §4.3 says to enforce it in the service layer and test it.
"""

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ResultEntry, TermHalf, UserRole
from tests.integration.test_admin_academic import make_session

CLASSES = "/api/v1/classes"
HOUSES = "/api/v1/houses"
SUBJECTS = "/api/v1/subjects"


async def a_class(client: AsyncClient, headers, *, name="Primary 4", level_order=4) -> dict:
    response = await client.post(
        CLASSES, headers=headers, json={"name": name, "level_order": level_order}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def a_subject(client: AsyncClient, headers, **payload) -> dict:
    response = await client.post(SUBJECTS, headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Classes and houses
# ---------------------------------------------------------------------------


async def test_an_admin_creates_a_class(client: AsyncClient, admin_headers) -> None:
    body = await a_class(client, admin_headers)

    assert body["name"] == "Primary 4"
    assert body["is_active"] is True


async def test_classes_list_in_level_order(client: AsyncClient, admin_headers) -> None:
    """Display order only — never a ranking of anything (R11)."""
    await a_class(client, admin_headers, name="Primary 5", level_order=5)
    await a_class(client, admin_headers, name="Primary 1", level_order=1)

    listed = (await client.get(CLASSES, headers=admin_headers)).json()

    assert [item["name"] for item in listed] == ["Primary 1", "Primary 5"]


async def test_a_duplicate_class_name_is_a_conflict(client: AsyncClient, admin_headers) -> None:
    await a_class(client, admin_headers)

    response = await client.post(
        CLASSES, headers=admin_headers, json={"name": "Primary 4", "level_order": 4}
    )

    assert response.status_code == 409


async def test_an_admin_creates_a_house(client: AsyncClient, admin_headers) -> None:
    response = await client.post(HOUSES, headers=admin_headers, json={"name": "Blue"})

    assert response.status_code == 201
    assert response.json()["name"] == "Blue"


async def test_a_duplicate_house_name_is_a_conflict(client: AsyncClient, admin_headers) -> None:
    await client.post(HOUSES, headers=admin_headers, json={"name": "Blue"})

    response = await client.post(HOUSES, headers=admin_headers, json={"name": "Blue"})

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


async def test_the_english_group_and_its_children(client: AsyncClient, admin_headers) -> None:
    """§1.5: English is a heading over five scored sub-subjects."""
    english = await a_subject(client, admin_headers, name="English", is_group=True)
    child = await a_subject(
        client,
        admin_headers,
        name="Language Arts",
        parent_subject_id=english["id"],
        display_order=1,
    )

    assert english["is_group"] is True
    assert child["parent_subject_id"] == english["id"]
    assert child["is_group"] is False


async def test_a_group_cannot_sit_under_another_subject(client: AsyncClient, admin_headers) -> None:
    english = await a_subject(client, admin_headers, name="English", is_group=True)

    response = await client.post(
        SUBJECTS,
        headers=admin_headers,
        json={"name": "Nested", "is_group": True, "parent_subject_id": english["id"]},
    )

    assert response.status_code == 422
    assert "cannot sit under another subject" in response.json()["detail"]


async def test_a_subject_cannot_sit_under_a_non_group(client: AsyncClient, admin_headers) -> None:
    """English is the only grouping on the card."""
    maths = await a_subject(client, admin_headers, name="Mathematics")

    response = await client.post(
        SUBJECTS,
        headers=admin_headers,
        json={"name": "Algebra", "parent_subject_id": maths["id"]},
    )

    assert response.status_code == 422
    assert "not a group heading" in response.json()["detail"]


async def test_a_group_cannot_be_specialist(client: AsyncClient, admin_headers) -> None:
    """A heading carries no scores, so it has no teacher to specialise."""
    response = await client.post(
        SUBJECTS,
        headers=admin_headers,
        json={"name": "English", "is_group": True, "is_specialist": True},
    )

    assert response.status_code == 422


async def test_the_specialist_flag_is_the_schools_to_set(
    client: AsyncClient, admin_headers
) -> None:
    """§2.3: which subjects are specialist is data, never a hardcoded list."""
    computer = await a_subject(client, admin_headers, name="Computer", is_specialist=True)

    assert computer["is_specialist"] is True

    response = await client.patch(
        f"{SUBJECTS}/{computer['id']}", headers=admin_headers, json={"is_specialist": False}
    )

    assert response.status_code == 200
    assert response.json()["is_specialist"] is False


async def test_a_subject_can_be_renamed_and_reordered(client: AsyncClient, admin_headers) -> None:
    """§1.5: "the list must be admin-editable and the display order must be
    configurable"."""
    subject = await a_subject(client, admin_headers, name="Computer", display_order=9)

    response = await client.patch(
        f"{SUBJECTS}/{subject['id']}",
        headers=admin_headers,
        json={"name": "Computer Studies", "display_order": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Computer Studies"
    assert body["display_order"] == 3


async def test_a_subject_is_retired_rather_than_deleted(client: AsyncClient, admin_headers) -> None:
    """Past cards still cite it, so there is no delete endpoint."""
    subject = await a_subject(client, admin_headers, name="Latin")

    await client.patch(
        f"{SUBJECTS}/{subject['id']}", headers=admin_headers, json={"is_active": False}
    )

    active = (await client.get(SUBJECTS, headers=admin_headers)).json()
    everything = (
        await client.get(SUBJECTS, headers=admin_headers, params={"include_inactive": True})
    ).json()

    assert subject["id"] not in [item["id"] for item in active]
    assert subject["id"] in [item["id"] for item in everything]


# ---------------------------------------------------------------------------
# What a class offers — R7
# ---------------------------------------------------------------------------


async def test_setting_a_classs_subject_list(client: AsyncClient, admin_headers) -> None:
    await make_session(client, admin_headers)
    klass = await a_class(client, admin_headers)
    maths = await a_subject(client, admin_headers, name="Mathematics")
    french = await a_subject(client, admin_headers, name="French")

    response = await client.put(
        f"{CLASSES}/{klass['id']}/subjects",
        headers=admin_headers,
        json={"subject_ids": [maths["id"], french["id"]]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["subject_id"] for item in body] == [maths["id"], french["id"]]
    assert [item["display_order"] for item in body] == [0, 1]


async def test_a_group_subject_cannot_be_offered_to_a_class(
    client: AsyncClient, admin_headers
) -> None:
    """R7, the rule this whole endpoint exists to protect."""
    await make_session(client, admin_headers)
    klass = await a_class(client, admin_headers)
    english = await a_subject(client, admin_headers, name="English", is_group=True)

    response = await client.put(
        f"{CLASSES}/{klass['id']}/subjects",
        headers=admin_headers,
        json={"subject_ids": [english["id"]]},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "group heading" in detail
    assert "sub-subjects instead" in detail


async def test_a_retired_subject_cannot_be_offered(client: AsyncClient, admin_headers) -> None:
    await make_session(client, admin_headers)
    klass = await a_class(client, admin_headers)
    subject = await a_subject(client, admin_headers, name="Latin")
    await client.patch(
        f"{SUBJECTS}/{subject['id']}", headers=admin_headers, json={"is_active": False}
    )

    response = await client.put(
        f"{CLASSES}/{klass['id']}/subjects",
        headers=admin_headers,
        json={"subject_ids": [subject["id"]]},
    )

    assert response.status_code == 422
    assert "retired" in response.json()["detail"]


async def test_the_subject_list_is_replaced_not_merged(client: AsyncClient, admin_headers) -> None:
    await make_session(client, admin_headers)
    klass = await a_class(client, admin_headers)
    maths = await a_subject(client, admin_headers, name="Mathematics")
    french = await a_subject(client, admin_headers, name="French")

    await client.put(
        f"{CLASSES}/{klass['id']}/subjects",
        headers=admin_headers,
        json={"subject_ids": [maths["id"], french["id"]]},
    )
    response = await client.put(
        f"{CLASSES}/{klass['id']}/subjects",
        headers=admin_headers,
        json={"subject_ids": [maths["id"]]},
    )

    assert [item["subject_id"] for item in response.json()] == [maths["id"]]


async def test_a_subject_with_scores_cannot_be_removed_from_a_class(
    client: AsyncClient, admin_headers, world, session: AsyncSession
) -> None:
    """Removing the offering would orphan every score entered against it."""
    from app.models import AssessmentPeriod

    period = AssessmentPeriod(
        school_id=world.school.id, term_id=world.term.id, half=TermHalf.FIRST_HALF
    )
    session.add(period)
    await session.flush()
    session.add(
        ResultEntry(
            school_id=world.school.id,
            assessment_period_id=period.id,
            pupil_id=world.pupils["ada"].id,
            class_subject_id=world.maths_4a.id,
            ca_test_1=Decimal(7),
        )
    )
    await session.commit()

    response = await client.put(
        f"{CLASSES}/{world.class_4a.id}/subjects",
        headers=admin_headers,
        json={"subject_ids": []},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "Scores have already been entered" in detail
    assert "Retire the subject instead" in detail


async def test_offering_subjects_needs_a_current_session(
    client: AsyncClient, admin_headers
) -> None:
    """Silently defaulting to the latest session would attach a whole subject
    list to the wrong year, unnoticed until the cards printed."""
    klass = await a_class(client, admin_headers)
    maths = await a_subject(client, admin_headers, name="Mathematics")

    response = await client.put(
        f"{CLASSES}/{klass['id']}/subjects",
        headers=admin_headers,
        json={"subject_ids": [maths["id"]]},
    )

    assert response.status_code == 409
    assert "No academic session is current" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Teachers
# ---------------------------------------------------------------------------


async def test_assigning_a_subject_teacher(client: AsyncClient, admin_headers, make_user) -> None:
    await make_session(client, admin_headers)
    klass = await a_class(client, admin_headers)
    maths = await a_subject(client, admin_headers, name="Mathematics")
    offerings = (
        await client.put(
            f"{CLASSES}/{klass['id']}/subjects",
            headers=admin_headers,
            json={"subject_ids": [maths["id"]]},
        )
    ).json()
    teacher = await make_user(UserRole.TEACHER)

    response = await client.put(
        f"/api/v1/class-subjects/{offerings[0]['id']}/teacher",
        headers=admin_headers,
        json={"teacher_user_id": str(teacher.id)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["teacher_user_id"] == str(teacher.id)


async def test_reassigning_replaces_the_teacher(
    client: AsyncClient, admin_headers, make_user
) -> None:
    """One teacher per class-subject (§4.3) — the unique constraint makes a
    second assignment an update, not a conflict."""
    await make_session(client, admin_headers)
    klass = await a_class(client, admin_headers)
    maths = await a_subject(client, admin_headers, name="Mathematics")
    offerings = (
        await client.put(
            f"{CLASSES}/{klass['id']}/subjects",
            headers=admin_headers,
            json={"subject_ids": [maths["id"]]},
        )
    ).json()
    first = await make_user(UserRole.TEACHER)
    second = await make_user(UserRole.TEACHER)

    url = f"/api/v1/class-subjects/{offerings[0]['id']}/teacher"
    await client.put(url, headers=admin_headers, json={"teacher_user_id": str(first.id)})
    response = await client.put(
        url, headers=admin_headers, json={"teacher_user_id": str(second.id)}
    )

    assert response.status_code == 200
    assert response.json()["teacher_user_id"] == str(second.id)


async def test_a_parent_cannot_be_assigned_to_teach(
    client: AsyncClient, admin_headers, make_user
) -> None:
    await make_session(client, admin_headers)
    klass = await a_class(client, admin_headers)
    maths = await a_subject(client, admin_headers, name="Mathematics")
    offerings = (
        await client.put(
            f"{CLASSES}/{klass['id']}/subjects",
            headers=admin_headers,
            json={"subject_ids": [maths["id"]]},
        )
    ).json()
    parent = await make_user(UserRole.PARENT)

    response = await client.put(
        f"/api/v1/class-subjects/{offerings[0]['id']}/teacher",
        headers=admin_headers,
        json={"teacher_user_id": str(parent.id)},
    )

    assert response.status_code == 422
    assert "not a teacher" in response.json()["detail"]


async def test_a_deactivated_teacher_cannot_be_assigned(
    client: AsyncClient, admin_headers, make_user
) -> None:
    await make_session(client, admin_headers)
    klass = await a_class(client, admin_headers)
    retired = await make_user(UserRole.TEACHER, is_active=False)

    response = await client.put(
        f"{CLASSES}/{klass['id']}/class-teacher",
        headers=admin_headers,
        json={"teacher_user_id": str(retired.id)},
    )

    assert response.status_code == 422
    assert "deactivated" in response.json()["detail"]


async def test_assigning_a_class_teacher(client: AsyncClient, admin_headers, make_user) -> None:
    """§5.2 hands this person the narrative, attendance, growth, the class
    teacher's comment and the submission gate."""
    academic = await make_session(client, admin_headers)
    klass = await a_class(client, admin_headers)
    teacher = await make_user(UserRole.TEACHER)

    response = await client.put(
        f"{CLASSES}/{klass['id']}/class-teacher",
        headers=admin_headers,
        json={"teacher_user_id": str(teacher.id)},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["teacher_user_id"] == str(teacher.id)
    assert body["academic_session_id"] == academic["id"]


async def test_a_class_has_one_class_teacher_per_session(
    client: AsyncClient, admin_headers, make_user
) -> None:
    await make_session(client, admin_headers)
    klass = await a_class(client, admin_headers)
    first = await make_user(UserRole.TEACHER)
    second = await make_user(UserRole.TEACHER)

    url = f"{CLASSES}/{klass['id']}/class-teacher"
    original = (
        await client.put(url, headers=admin_headers, json={"teacher_user_id": str(first.id)})
    ).json()
    replacement = (
        await client.put(url, headers=admin_headers, json={"teacher_user_id": str(second.id)})
    ).json()

    assert original["id"] == replacement["id"]
    assert replacement["teacher_user_id"] == str(second.id)


async def test_a_teacher_from_another_school_is_a_404(
    client: AsyncClient, admin_headers, session: AsyncSession
) -> None:
    """§5.2: outside the caller's scope is a 404, not a 403. A 403 would
    confirm the account exists."""
    from app.models import School, User

    other_school = School(name="Another School", short_name="AS")
    session.add(other_school)
    await session.flush()
    outsider = User(
        school_id=other_school.id,
        role=UserRole.TEACHER,
        full_name="Outside Teacher",
        email="outsider@elsewhere.test",
        password_hash="x",
        must_change_password=False,
    )
    session.add(outsider)
    await session.commit()

    await make_session(client, admin_headers)
    klass = await a_class(client, admin_headers)

    response = await client.put(
        f"{CLASSES}/{klass['id']}/class-teacher",
        headers=admin_headers,
        json={"teacher_user_id": str(outsider.id)},
    )

    assert response.status_code == 404
